"""v1.4 방법·모델 비교 판정(compare.py) 테스트 — 가짜 모델로 만든 실행 기록을 판정한다."""

import json
from pathlib import Path

import pytest

from test_pipeline_methods import NO_ALL, FakeClient, run_fake
from triage_eval.pipeline import compare as cmp
from triage_eval.pipeline import gate as g

ROOT = Path(__file__).resolve().parent.parent
SEEDS = (1, 11, 21)


@pytest.fixture
def crit():
    return cmp.load_criteria(cmp.CRITERIA)


def test_committed_criteria_load_and_match_plan(crit):
    """사전 등록한 기준 파일이 읽히고, 계획서의 핵심 값과 같다."""
    assert crit["meta"]["seeds"] == [1, 11, 21] and crit["meta"]["split"] == "dev"
    assert crit["relative_to_baseline"] == {"x2_miss_increase_max": 0, "x3_miss_increase_max": 0}
    assert crit["regression"]["x1_miss_increase_max"] == 0
    assert crit["regression"]["field_drop_max_responses"]["처리"] == 0
    assert crit["absolute"]["latency_max_sec"] == 10.0


def test_unknown_key_in_criteria_is_rejected(tmp_path):
    bad = tmp_path / "c.toml"
    bad.write_text(cmp.CRITERIA.read_text(encoding="utf-8") + "\n[absolute2]\nx = 1\n", encoding="utf-8")
    with pytest.raises(g.GateError):
        cmp.load_criteria(bad)


def _runs(monkeypatch, tmp_path, method, client_factory=FakeClient, models=("fake",)):
    return [run_fake(monkeypatch, tmp_path, method, s, client_factory(), models) for s in SEEDS]


def test_identical_answers_keep_baseline(monkeypatch, tmp_path, crit):
    """후보가 기준과 똑같이 답하면 기준을 통과해도 개선이 없으므로 기준 유지(종료 코드 1)."""
    logs = _runs(monkeypatch, tmp_path, "m0") + _runs(monkeypatch, tmp_path, "m1")
    assert cmp.run(logs, crit, "a", baseline="m0/fake", write=False) == 1


def test_fewer_x1_misses_is_adopted(monkeypatch, tmp_path, crit):
    """기준이 Critical 한 건(S04b)을 놓치고 후보가 잡으면 채택(종료 코드 0)."""
    miss = {"S04b": {"우선순위": "Major", "처리": "등록(재현 대기)"}}
    base = _runs(monkeypatch, tmp_path, "m0", lambda: FakeClient(override=miss))
    cand = _runs(monkeypatch, tmp_path, "m2", lambda: FakeClient(override=miss, answers_for={"S04b": {**NO_ALL, "q4": "예"}}))
    assert cmp.run(base + cand, crit, "a", baseline="m0/fake", write=False) == 0


def test_yes_biased_checklist_is_rejected(monkeypatch, tmp_path, crit):
    """체크리스트에 모두 '예'로 답하는 모델(계획 §4 '예' 편향)은 과잉 상신·처리 하락으로 탈락한다."""
    base = _runs(monkeypatch, tmp_path, "m0")
    cand = _runs(monkeypatch, tmp_path, "m2", lambda: FakeClient(answers={**NO_ALL, "q4": "예"}))
    assert cmp.run(base + cand, crit, "a", baseline="m0/fake", write=False) == 1


def test_more_x3_than_baseline_fails(monkeypatch, tmp_path, crit):
    """X-3는 기준선보다 늘면 탈락(계획 §3 기준선 대비)."""
    close = {"A20": {"처리": "폐기"}}   # 경계 건(사람 검토 필요)을 폐기
    base = _runs(monkeypatch, tmp_path, "m0")
    cand = _runs(monkeypatch, tmp_path, "m1", lambda: FakeClient(override=close))
    assert cmp.run(base + cand, crit, "a", baseline="m0/fake", write=False) == 1


def test_missing_seed_cannot_be_judged(monkeypatch, tmp_path, crit):
    logs = _runs(monkeypatch, tmp_path, "m0") + _runs(monkeypatch, tmp_path, "m1")[:2]
    with pytest.raises(g.GateError, match="seed 구성"):
        cmp.run(logs, crit, "a", baseline="m0/fake", write=False)


def test_different_conditions_cannot_be_judged(monkeypatch, tmp_path, crit):
    logs = _runs(monkeypatch, tmp_path, "m0") + _runs(monkeypatch, tmp_path, "m1")
    data = json.loads(logs[-1].read_text(encoding="utf-8"))
    data["metadata"]["run_config"]["guardrail_version"] = None   # --no-guardrail 로 돌린 실행이 섞임
    logs[-1].write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(g.GateError, match="후처리 안전장치"):
        cmp.run(logs, crit, "a", baseline="m0/fake", write=False)


def test_final_split_is_rejected(monkeypatch, tmp_path, crit):
    logs = _runs(monkeypatch, tmp_path, "m0") + _runs(monkeypatch, tmp_path, "m1")
    data = json.loads(logs[0].read_text(encoding="utf-8"))
    data["results"][0]["split"] = "final"
    logs[0].write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(g.GateError, match="개발용이 아닌"):
        cmp.run(logs, crit, "a", baseline="m0/fake", write=False)


def test_model_comparison_arms(monkeypatch, tmp_path, crit):
    """실험 B — 같은 방법, 한 실행 안의 두 모델을 arm으로 나눠 비교한다."""
    logs = _runs(monkeypatch, tmp_path, "m2", models=("fake", "fake2"))
    assert cmp.run(logs, crit, "b", baseline="m2/fake", write=False) == 1


def test_conditional_note_when_both_methods_eligible(crit):
    ok = {"all_seeds_passed": True, "x1_base": 3, "x1_cand": 1, "pri_base": 10, "pri_cand": 10, "latency_cand": 5}
    note = cmp.conditional_note(crit, {"m1/q": ok, "m2/q": ok}, ["m0/q", "m1/q", "m2/q"])
    assert note and "m1m2" in note
    assert cmp.conditional_note(crit, {"m1/q": ok, "m2/q": ok}, ["m0/q", "m1/q", "m2/q", "m1m2/q"]) is None
