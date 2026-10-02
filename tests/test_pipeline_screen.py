"""screen.py 테스트 — 평가용 문항 차단, 판정 로직, 가짜 클라이언트로 점검 흐름 전체."""

import json

import pytest

from triage_eval.pipeline import screen
from triage_eval.pipeline.run import DATASET

DATA = json.loads(DATASET.read_text(encoding="utf-8"))
GOOD = "\n".join(["[요약]: 결제 후 재화 미지급", "[분류]: 결함", "[모듈]: 결제·재화", "[우선순위]: Critical",
                  "[재현 정보]: 충분", "[발생 빈도]: 1회", "[처리]: 긴급 사인 요청", "[누락 정보 및 권장 조치]: 결제 로그 확인"])


def test_pick_items_uses_dev_only():
    """설계 의도 1 — 고른 문항은 모두 개발용이다."""
    items = screen.pick_items(DATA)
    assert len(items) == 3 and all(i["split"] == "dev" for i in items)
    assert {(i["set"], i["track"]) for i in items[:2]} == {("representative", "A"), ("representative", "B")}
    assert items[2]["set"] == "focused"


def test_pick_items_never_returns_test_items():
    """개발용 문항이 없으면 평가용으로 대신 채우지 않고 멈춘다."""
    only_test = {"items": [i for i in DATA["items"] if i["split"] == "test"]}
    with pytest.raises(RuntimeError):
        screen.pick_items(only_test)


def test_judge_thinking():
    assert screen.judge_thinking(GOOD, None)[0]
    assert screen.judge_thinking(GOOD, "")[0]
    assert not screen.judge_thinking(GOOD, "먼저 분류를 생각해 보면...")[0]
    assert not screen.judge_thinking("<think>음</think>\n" + GOOD, None)[0]


def test_judge_gpu():
    assert screen.judge_gpu({"size": 6 * 2**30, "size_vram": 6 * 2**30})[0] is True
    ok, note = screen.judge_gpu({"size": 8 * 2**30, "size_vram": 7 * 2**30})
    assert ok is False and "1024 MiB" in note
    assert screen.judge_gpu(None)[0] is None  # 판정 불가는 FAIL과 구분한다


def test_judge_gpu_holds_on_implausible_size():
    """설계 의도 8 — ps 적재 크기가 모델 파일보다 작으면 PASS 대신 판정 불가 (gemma4:12b 896 MiB 사례)."""
    ok, note = screen.judge_gpu({"size": 896 * 2**20, "size_vram": 896 * 2**20}, disk_bytes=7_400_000_000)
    assert ok is None and "판정 불가" in note
    assert screen.judge_gpu({"size": 8 * 2**30, "size_vram": 8 * 2**30}, disk_bytes=7_400_000_000)[0] is True


def test_judge_structured():
    assert screen.judge_enum_json('{"분류": "결함", "우선순위": "Major"}', ["분류", "우선순위"])[0]
    assert not screen.judge_enum_json('{"분류": "무관 중", "우선순위": "Major"}', ["분류", "우선순위"])[0]
    assert not screen.judge_enum_json("분류: 결함", ["분류"])[0]
    assert screen.judge_pattern_json('{"요약": "보스전 진입 시 튕김"}', "요약")[0]
    assert not screen.judge_pattern_json('{"요약": "기기 과熱"}', "요약")[0]


def test_judge_format():
    assert screen.judge_format([GOOD, GOOD])[0]
    assert not screen.judge_format([GOOD, GOOD.replace("[처리]: 긴급 사인 요청\n", "")])[0]   # R2
    assert not screen.judge_format([GOOD.replace("미지급", "未지급")])[0]                     # R7


def test_overall():
    assert screen.overall({"a": {"pass": True}, "b": {"pass": True}}) == "PASS"
    assert screen.overall({"a": {"pass": True}, "b": {"pass": None}}) == "HOLD"
    assert screen.overall({"a": {"pass": None}, "b": {"pass": False}}) == "FAIL"


class FakeClient:
    """thinking 기능이 없는 모델처럼 think 인자를 거부하거나, 생각 과정을 내보내는 모델을 흉내 낸다."""

    def __init__(self, reject_think=False, thinks_by_default=False, spill_mib=0):
        self.reject_think, self.thinks_by_default, self.spill = reject_think, thinks_by_default, spill_mib
        self.calls = []

    def generate(self, model, prompt, options=None, think=None, format=None, keep_alive=None):
        self.calls.append({"think": think, "format": format, "keep_alive": keep_alive, "options": options})
        if keep_alive == 0:
            return {}
        if think is not None and self.reject_think:
            raise RuntimeError(f'"{model}" does not support thinking')
        thinking = "생각 중..." if (think is None and self.thinks_by_default) else None
        if format:
            props = format["properties"]
            body = {f: ("결함" if f == "분류" else "Major" if f == "우선순위" else "보스전 튕김") for f in props}
            return {"response": json.dumps(body, ensure_ascii=False), "thinking": thinking}
        return {"response": GOOD, "thinking": thinking}

    def ps(self):
        size = 6 * 2**30
        return {"models": [{"model": "m:1", "size": size, "size_vram": size - self.spill * 2**20}]}

    def show(self, model):
        return {"capabilities": ["completion"], "license": "Apache License\nVersion 2.0"}


ITEMS = screen.pick_items(DATA)


def test_screen_passes_and_uses_same_conditions():
    """설계 의도 3·4 — 모든 호출이 같은 옵션·seed를 쓰고, 시작과 끝에 모델을 내린다."""
    c = FakeClient()
    res = screen.screen_model(c, "m:1", ITEMS, "abc123")
    assert res["result"] == "PASS"
    gen = [x for x in c.calls if x["keep_alive"] != 0]
    assert all(x["options"]["seed"] == screen.SEED and x["options"]["num_ctx"] == 8192 for x in gen)
    assert c.calls[0]["keep_alive"] == 0 and c.calls[-1]["keep_alive"] == 0
    assert res["info"]["license_first_line"] == "Apache License"
    assert "score" not in json.dumps(res) and "accuracy" not in json.dumps(res)  # 설계 의도 2 — 정답률 미기록


def test_screen_records_think_rejection_without_failing():
    """설계 의도 5 — think 인자를 거부하는 모델은 거부 사실을 기록하고 think 없이 점검을 이어 간다."""
    res = screen.screen_model(FakeClient(reject_think=True), "m:1", ITEMS, "abc123")
    assert res["result"] == "PASS" and res["info"]["think_param_rejected"] is True


def test_screen_records_default_thinking():
    res = screen.screen_model(FakeClient(thinks_by_default=True), "m:1", ITEMS, "abc123")
    assert res["info"]["default_outputs_thinking"] is True
    assert res["checks"]["C2_think_off"]["pass"] is True  # think=False 로는 꺼진다


def test_screen_fails_on_cpu_spill():
    res = screen.screen_model(FakeClient(spill_mib=500), "m:1", ITEMS, "abc123")
    assert res["result"] == "FAIL" and res["checks"]["C3_gpu_fit"]["pass"] is False


def test_screen_holds_and_records_raw_ps_when_size_implausible():
    res = screen.screen_model(FakeClient(), "m:1", ITEMS, "abc123", disk_bytes=10 * 2**30)
    assert res["result"] == "HOLD" and res["checks"]["C3_gpu_fit"]["pass"] is None
    assert res["info"]["ps_raw"]["size"] == 6 * 2**30 and res["info"]["disk_bytes"] == 10 * 2**30


def test_screen_fails_when_not_installed():
    c = FakeClient()
    res = screen.screen_model(c, "m:1", ITEMS, None)
    assert res["result"] == "FAIL" and c.calls == []
