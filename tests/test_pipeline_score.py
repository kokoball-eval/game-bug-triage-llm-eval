"""정답 대조 채점 (score.py) 테스트 — 정답 라벨로 만든 응답과 일부러 틀린 응답으로 확인한다."""

import json
from pathlib import Path

from triage_eval.pipeline.score import aggregate, field_correct, score_one

ROOT = Path(__file__).resolve().parent.parent
ITEMS = {i["id"]: i for i in json.loads((ROOT / "data/eval_v13/aether_raid_v13.json").read_text(encoding="utf-8"))["items"]}


def ideal(item, **override):
    """정답 라벨의 첫 값(최선 답)으로 응답을 만든다."""
    lb = item["labels"]
    v = {f: lb[f][0] if lb[f] else "해당 없음" for f in ["분류", "모듈", "우선순위", "재현 정보", "발생 빈도", "처리"]}
    v.update(override)
    note = " / ".join(lb.get("must_request", []) + lb.get("must_recommend", [])) or "없음"
    return "\n".join([f"[요약]: {item['input']['title']}"] + [f"[{k}]: {x}" for k, x in v.items()]
                     + [f"[누락 정보 및 권장 조치]: {note}"])


def rec(item, text, model="m"):
    return {"eval_id": f"{model}_{item['id']}", "model": model, "run_index": 1, "item_id": item["id"],
            "success": True, "response_text": text, "elapsed_sec": 1.0, "prompt_eval_count": 1000}


def test_ideal_responses_score_perfectly_on_all_items():
    rows = [score_one(rec(i, ideal(i)), i) for i in ITEMS.values()]
    agg = aggregate(rows, ITEMS)
    assert agg["all_fields_ok_rate"] == 100.0 and agg["strict_rate"] == 100.0
    assert agg["risk_miss"] == {"X-1": 0, "X-2": 0, "X-3": 0} and agg["over_escalation"] == 0
    assert agg["required_coverage_rate"] == 100.0


def test_x1_miss_when_critical_not_sent_to_sign_request():
    item = ITEMS["B01"]  # Critical, 긴급 사인 요청
    r = score_one(rec(item, ideal(item, 처리="개발 배정")), item)
    assert r["risk_miss"] == ["X-1"]


def test_x2_miss_when_defect_discarded():
    item = ITEMS["A02"]  # 단문 크래시 — 결함, 정보 요청 후 보류
    assert "X-2" in score_one(rec(item, ideal(item, 처리="폐기")), item)["risk_miss"]


def test_x3_miss_when_boundary_case_closed():
    item = ITEMS["A20"]  # 경계 P-B4, 사람 검토 필요
    assert "X-3" in score_one(rec(item, ideal(item, 처리="폐기")), item)["risk_miss"]
    assert score_one(rec(item, ideal(item, 처리="정보 요청 후 보류")), item)["risk_miss"] == []


def test_over_escalation_counted():
    item = ITEMS["B10"]  # Trivial 오타
    r = score_one(rec(item, ideal(item, 처리="긴급 사인 요청", 우선순위="Critical")), item)
    assert r["over_escalation"] and r["risk_miss"] == []


def test_module_rules():
    assert field_correct("모듈", "해당 없음", []) == (True, True)
    assert field_correct("모듈", "결제·재화", []) == (False, False)
    assert field_correct("모듈", "플랫폼 호환성 / UI·텍스트", ["플랫폼 호환성", "UI·텍스트"]) == (True, True)
    assert field_correct("모듈", "UI·텍스트", ["플랫폼 호환성", "UI·텍스트"]) == (True, False)
    assert field_correct("모듈", "네트워크 / UI·텍스트", ["플랫폼 호환성", "UI·텍스트"])[0] is False


def test_unparsable_response_counts_as_wrong():
    item = ITEMS["B04"]
    r = score_one(rec(item, "모르겠습니다"), item)
    assert not r["all_fields_ok"] and not r["format"]["parsable_pass"]


def test_hallucinated_device_detected_but_context_quote_is_not():
    item = ITEMS["A03"]  # "pc로 로그인 안되는데" — 기기 정보 없음
    bad = ideal(item).replace(f"[요약]: {item['input']['title']}", "[요약]: 갤럭시 S25에서 로그인 불가")
    assert score_one(rec(item, bad), item)["hallucinated"]
    b14 = ITEMS["B14"]  # 입력에 '갤럭시 Z 폴드5'가 있음
    ok = ideal(b14).replace(f"[요약]: {b14['input']['title']}", "[요약]: 갤럭시 Z 폴드5 펼친 화면에서 스킬 버튼 잘림")
    assert not score_one(rec(b14, ok), b14)["hallucinated"]


def test_pipeline_end_to_end_with_fake_model(tmp_path, monkeypatch):
    """모델 대신 정답 응답을 돌려주는 가짜 클라이언트로 실행 → 채점까지 한 번에 돌린다."""
    from triage_eval.pipeline import run as pipeline_run
    from triage_eval.pipeline import score as pipeline_score

    by_title = {i["input"]["title"]: i for i in ITEMS.values()}

    class FakeClient:
        def generate(self, model, prompt, options):
            item = next((it for t, it in by_title.items() if f"[제목] {t}\n" in prompt), None)
            text = ideal(item) if item else "[요약]: 워밍업"
            return {"response": text, "eval_count": 100, "eval_duration": 10**9,
                    "load_duration": 0, "prompt_eval_count": 2000}

        def ps(self):
            return {"models": []}

        def list(self):
            return {"models": []}

    monkeypatch.setattr(pipeline_run.ollama, "Client", FakeClient)
    monkeypatch.setattr(pipeline_run, "preflight_snapshot", lambda c: {"warnings": [], "notes": []})
    monkeypatch.setattr(pipeline_run, "OUT_DIR", tmp_path / "history")
    assert pipeline_run.main(["--seed", "1", "--model", "fake", "--repeat", "1"]) == 0
    log = next((tmp_path / "history").glob("v13_dev_*.json"))
    assert pipeline_score.main(["--log", str(log), "--no-report"]) == 0
    result = json.loads(next(tmp_path.glob("score_*.json")).read_text(encoding="utf-8"))
    total = result["summary"]["fake"]["전체"]
    assert total["n"] == 32 and total["all_fields_ok_rate"] == 100.0 and total["risk_miss"]["X-1"] == 0
