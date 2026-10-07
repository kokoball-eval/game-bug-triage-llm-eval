"""v1.4 방법(methods.py, run.py --method) 테스트 — 모델은 호출하지 않는다."""

import json
import re
from pathlib import Path

import pytest

from triage_eval.pipeline import methods as m
from triage_eval.pipeline.contract import parse_v2, score_format_v2
from triage_eval.pipeline.prompt import (SYSTEM_PROMPT_V2, build_discard_check_prompt, build_input, build_prompt,
                                         build_retry_prompt)

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data/eval_v14/aether_raid_v14.json").read_text(encoding="utf-8"))
ITEMS = {i["id"]: i for i in DATA["items"]}


# ── M1 판정 예시 ─────────────────────────────────────────────

def test_examples_are_four_valid_responses_with_distinct_grades():
    pairs = m.load_examples()
    assert len(pairs) == 4
    grades, actions = set(), set()
    for _, out in pairs:
        assert score_format_v2(out)["strict_pass"], out
        v = parse_v2(out)
        grades.add(v["우선순위"])
        actions.add(v["처리"])
    assert grades == {"해당 없음", "판단보류", "Trivial", "Critical"}   # 계획 §2.1 — 한쪽으로 쏠리지 않게
    assert len(actions) == 4


def test_examples_read_same_from_crlf_checkout(tmp_path):
    """Windows 체크아웃(CRLF)에서도 같은 예시 문자열·지문이 나와야 한다 (methods.py 설계 의도 1)."""
    crlf = tmp_path / "m1_examples.md"
    crlf.write_bytes(m.EXAMPLES_DOC.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    assert m.load_examples(crlf) == m.load_examples()


def _content(text: str) -> str:
    """양식 칸 이름([본문], [테스트 환경] 등)과 공백을 빼고 내용만 남긴다."""
    lines = [re.sub(r"^\[[^\]]+\]\s*", "", ln) for ln in text.splitlines()]
    return re.sub(r"\s+", "", "".join(lines))


def _grams(s: str, n: int = 6) -> set[str]:
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def test_examples_do_not_reuse_eval_item_text():
    """계획 §4 — 예시가 평가셋 88건의 표현을 옮겨 쓰지 않았는지 (6글자 조각 겹침 15% 미만)."""
    bodies = {i["id"]: _grams(_content(i["input"]["title"] + "\n" + i["input"]["body"])) for i in DATA["items"]}
    for inp, _ in m.load_examples():
        g = _grams(_content(inp.split("[제목]", 1)[1]))
        worst = max(len(g & b) / len(g) for b in bodies.values())
        assert worst < 0.15, (inp[:40], worst)


# ── 프롬프트: M0는 그대로 ───────────────────────────────────

def test_m0_prompts_unchanged():
    item = ITEMS["B04"]
    assert build_prompt(item) == f"{SYSTEM_PROMPT_V2}\n[리포트]\n{build_input(item)}"
    assert build_retry_prompt(item, "x", [("분류", "무관 중")]) == build_retry_prompt(item, "x", [("분류", "무관 중")], examples="")
    assert build_discard_check_prompt(item) == build_discard_check_prompt(item, "")


def test_m1_prompt_puts_examples_between_rules_and_report():
    item = ITEMS["A01"]
    p = build_prompt(item, m.examples_block())
    assert p.startswith(SYSTEM_PROMPT_V2)
    assert p.index("[예시 4 응답]") < p.index("\n[리포트]\n")
    assert p.endswith(build_input(item))


# ── M2 Critical 체크리스트 ───────────────────────────────────

NO_ALL = {**{k: "아니오" for k in m.CHECKLIST_KEYS}}
BASE = {"분류": "결함", "우선순위": "Major", "재현 정보": "충분"}


def test_checklist_has_six_questions_and_strict_schema():
    assert len(m.CHECKLIST) == 6 and m.CHECKLIST_SCHEMA["required"] == m.CHECKLIST_KEYS
    assert m.CHECKLIST_SCHEMA["properties"]["q6"]["enum"] == ["서버 장애", "민감한 텍스트", "아니오"]


@pytest.mark.parametrize("pred,answers,expected", [
    (BASE, {**NO_ALL, "q4": "예"}, True),                                   # 반복 악용 → 올림
    (BASE, NO_ALL, False),                                                  # 모두 아니오
    (BASE, {**NO_ALL, "q6": "민감한 텍스트"}, True),
    ({**BASE, "재현 정보": "부족"}, {**NO_ALL, "q1": "예"}, False),          # H-3a — 정보 부족 단문은 올리지 않음
    ({**BASE, "재현 정보": "부족"}, {**NO_ALL, "q6": "서버 장애"}, True),    # H-1b 예외
    ({**BASE, "재현 정보": "부족"}, {**NO_ALL, "q6": "민감한 텍스트"}, False),
    ({**BASE, "우선순위": "Critical"}, NO_ALL, False),                       # 내리지 않음
    ({**BASE, "우선순위": "중간"}, {**NO_ALL, "q2": "예"}, False),            # 허용 값 밖은 덮지 않음
    (BASE, {}, False),                                                      # 답을 읽지 못함
])
def test_decide_upgrade(pred, answers, expected):
    assert m.decide_upgrade(pred, answers)[0] is expected


def test_should_ask_only_defects():
    assert m.should_ask({"분류": "결함"})
    assert not m.should_ask({"분류": "중복 의심"}) and not m.should_ask({"분류": "문의·건의"})


def test_apply_upgrade_changes_priority_line_only():
    text = "[요약]: x\n[분류]: 결함\n[모듈]: 결제·재화\n[우선순위]: Major\n[재현 정보]: 충분"
    out = m.apply_upgrade(text)
    assert parse_v2(out)["우선순위"] == "Critical"
    assert out.replace("Critical", "Major") == text


def test_assets_fingerprint_per_method():
    assert m.assets_sha256("m0") is None
    shas = {m.assets_sha256(k) for k in ("m1", "m2", "m1m2")}
    assert len(shas) == 3


# ── run.py 연결 ───────────────────────────────────────────────

class FakeClient:
    """정답 라벨로 응답하는 가짜 모델. 체크리스트 질문에는 answers 를 JSON으로 돌려준다."""

    def __init__(self, answers=None, override=None, answers_for=None):
        self.answers = answers or NO_ALL
        self.answers_for = answers_for or {}   # 문항별 체크리스트 답 (없으면 answers)
        self.override = override or {}
        self.prompts = []
        self.by_title = {i["input"]["title"]: i for i in DATA["items"] if i["split"] == "dev"}

    def generate(self, model, prompt, options=None, think=None, keep_alive=None, format=None):
        if keep_alive == 0:
            return {}
        self.prompts.append(prompt)
        report = prompt.rsplit("\n[리포트]\n", 1)[1]
        item = next((it for t, it in self.by_title.items() if f"[제목] {t}\n" in report), None)
        if "[Critical 확인 질문]" in prompt:
            ans = self.answers_for.get(item["id"], self.answers) if item else self.answers
            return {"response": json.dumps(ans, ensure_ascii=False), "eval_count": 10, "eval_duration": 10**8,
                    "load_duration": 0, "prompt_eval_count": 3000}
        if item is None:
            text = "[요약]: 워밍업"
        else:
            lb = item["labels"]
            v = {f: lb[f][0] if lb[f] else "해당 없음" for f in ["분류", "모듈", "우선순위", "재현 정보", "발생 빈도", "처리"]}
            v.update(self.override.get(item["id"], {}))
            text = "\n".join([f"[요약]: {item['input']['title']}"] + [f"[{k}]: {x}" for k, x in v.items()]
                             + ["[누락 정보 및 권장 조치]: " + (" / ".join(lb["must_request"] + lb["must_recommend"]) or "없음")])
        return {"response": text, "eval_count": 100, "eval_duration": 10**9, "load_duration": 0, "prompt_eval_count": 2000}

    def ps(self):
        return {"models": []}

    def list(self):
        return {"models": []}


def test_critical_check_upgrades_and_records():
    from triage_eval.pipeline import run as pr
    item = ITEMS["S04b"]   # 정답 Critical — 첫 응답을 Major로 바꿔 놓고 체크리스트가 올리는지 본다
    client = FakeClient(answers={**NO_ALL, "q4": "예"}, override={"S04b": {"우선순위": "Major", "처리": "등록(재현 대기)"}})
    res = pr.generate_triage(client, "fake", item, dict(pr.OPTIONS_V2), method="m2")
    assert res["critical_checked"] and res["critical_upgraded"]
    assert parse_v2(res["response_text"])["우선순위"] == "Critical"
    att = [a for a in res["attempts"] if a["kind"] == "critical_check"][0]
    assert att["answers"]["q4"] == "예" and att["upgraded"]


def test_m0_makes_no_checklist_call_and_same_first_prompt():
    from triage_eval.pipeline import run as pr
    item = ITEMS["B04"]
    c0 = FakeClient()
    pr.generate_triage(c0, "fake", item, dict(pr.OPTIONS_V2), method="m0")
    assert c0.prompts[0] == build_prompt(item)
    assert not any("[Critical 확인 질문]" in p for p in c0.prompts)
    c1 = FakeClient()
    pr.generate_triage(c1, "fake", item, dict(pr.OPTIONS_V2), method="m1")
    assert c1.prompts[0] == build_prompt(item, m.examples_block())


def test_non_m0_method_requires_v14():
    from triage_eval.pipeline import run as pr
    assert pr.main(["--method", "m1"]) == 2


def run_fake(monkeypatch, tmp_path, method, seed, client=None, models=("fake",)):
    from triage_eval.pipeline import run as pr
    monkeypatch.setattr(pr.ollama, "Client", lambda: client or FakeClient())
    monkeypatch.setattr(pr, "preflight_snapshot", lambda c: {"warnings": [], "notes": []})
    monkeypatch.setattr(pr, "get_model_digests", lambda c, ms: {x: "sha-" + x for x in ms})
    out = tmp_path / "history" / f"{method}_{seed}_{len(list(tmp_path.glob('history/*')))}"  # 같은 초에 실행돼도 겹치지 않게
    monkeypatch.setattr(pr, "OUT_DIR_V14", out)
    args = ["--dataset", "v14", "--method", method, "--seed", str(seed)]
    for x in models:
        args += ["--model", x]
    assert pr.main(args) == 0
    (new,) = out.glob("*.json")
    return new


def test_v14_m2_end_to_end(monkeypatch, tmp_path):
    log = run_fake(monkeypatch, tmp_path, "m2", 1)
    assert log.name.startswith("v14_dev_m2_")
    cfg = json.loads(log.read_text(encoding="utf-8"))["metadata"]["run_config"]
    assert cfg["method"] == "m2" and cfg["method_assets_sha256"] == m.assets_sha256("m2")
    assert cfg["critical_check_policy"]["rule"] == "upgrade_only"


class UnloadRecordingClient(FakeClient):
    """모델을 내리는 호출(keep_alive=0)과 일반 호출의 순서를 기록한다."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = []

    def generate(self, model, prompt, options=None, think=None, keep_alive=None, format=None):
        self.calls.append(("unload" if keep_alive == 0 else "generate", model))
        return super().generate(model, prompt, options, think, keep_alive, format)


def test_run_unloads_every_model_after_last_response(monkeypatch, tmp_path):
    """run.py 설계 의도 13 (ISSUE-011) — 마지막 응답 뒤에 사용한 모델을 모두 내린다."""
    client = UnloadRecordingClient()
    run_fake(monkeypatch, tmp_path, "m2", 1, client=client, models=("fake-a", "fake-b"))
    last_generate = max(i for i, (kind, _) in enumerate(client.calls) if kind == "generate")
    tail = client.calls[last_generate + 1:]
    assert tail == [("unload", "fake-a"), ("unload", "fake-b")]
