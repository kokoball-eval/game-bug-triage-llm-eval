"""compare_runs.py 회귀 게이트 테스트.

v1.1 때 손으로 돌려 본 시나리오(T1~T6)를 자동 테스트로 옮겼다.
게이트는 "나쁜 것을 통과시키지 않는 것"이 핵심이므로, 통과 사례보다 실패 사례를 더 많이 둔다.
"""

import copy
import tomllib

import pytest

import compare_runs as cr
from compare_runs import (
    ComparabilityError, CriteriaError, compute_metrics, check_comparability,
    evaluate_gate, formal_rows, latest_history, validate_criteria, verdict_changes,
)
from summarize_eval import aggregate_local

from conftest import LLAMA, QWEN, ROOT

CRITERIA_FILE = ROOT / "gate_criteria.toml"


@pytest.fixture(scope="module")
def criteria() -> dict:
    with CRITERIA_FILE.open("rb") as f:
        return tomllib.load(f)


def gate(base: dict, cand: dict, criteria: dict, model: str = QWEN) -> dict:
    """두 로그를 판정해서 {기준 id: 통과 여부} 로 돌려주는 도우미."""
    checks = evaluate_gate(
        compute_metrics(formal_rows(base, model)),
        compute_metrics(formal_rows(cand, model)),
        criteria,
    )
    return {c["id"]: c["passed"] for c in checks}


def qwen_rows(payload: dict) -> list[dict]:
    return [r for r in payload["results"] if r["model"] == QWEN]


# ── 1. 지표 정의가 기존 스크립트와 같은가 ───────────────────

def test_metrics_match_summarize_eval(baseline):
    """compare_runs 와 summarize_eval 이 같은 로그에서 같은 숫자를 내야 한다 (설계 의도 2)."""
    mine = compute_metrics(formal_rows(baseline, QWEN))
    theirs = aggregate_local(baseline)[QWEN]
    for key in ("latency_sec", "tokens_per_sec", "eval_count"):
        assert mine[key] == theirs[key], key


# ── 2. 판정 (T1~T3) ───────────────────────────────────────

def test_identical_runs_pass_every_check(baseline, criteria):          # T1
    assert all(gate(baseline, copy.deepcopy(baseline), criteria).values())


def test_bad_baseline_is_caught_by_absolute_criteria(baseline, criteria):   # T2
    """Llama 끼리 비교하면 회귀 기준은 전부 통과(변화 0)하지만 절대 기준에서 걸려야 한다."""
    result = gate(baseline, copy.deepcopy(baseline), criteria, model=LLAMA)
    assert result["strict_rate_min"] is False
    assert result["latency_increase_max_pct"] is True


def test_latency_regression_fails(baseline, criteria):                  # T3
    cand = copy.deepcopy(baseline)
    for r in qwen_rows(cand):
        r["elapsed_sec"] *= 1.3
    assert gate(baseline, cand, criteria)["latency_increase_max_pct"] is False


def test_exactly_at_tolerance_passes(baseline, criteria):
    """허용폭과 정확히 같은 +20% 는 통과여야 한다.

    반올림 없이 비교하면 부동소수점 오차로 20.000000000000004% 가 되어 FAIL 이 났다.
    이 테스트가 처음 잡아낸 버그다 (compare_runs.py 설계 의도 9).
    """
    cand = copy.deepcopy(baseline)
    for r in qwen_rows(cand):
        r["elapsed_sec"] *= 1.2
    assert gate(baseline, cand, criteria)["latency_increase_max_pct"] is True


def test_single_preamble_is_caught_even_when_strict_rate_allows_it(baseline, criteria):
    """STRICT 95% 는 1건 실패를 허용하지만, 그 1건이 서두 사족이면 R1 기준이 따로 막아야 한다."""
    cand = copy.deepcopy(baseline)
    target = qwen_rows(cand)[0]
    target["response_text"] = "분석 결과입니다.\n" + target["response_text"]
    result = gate(baseline, cand, criteria)
    assert result["strict_rate_min"] is True
    assert result["preamble_fail_max"] is False


def test_missing_measurement_fails_instead_of_passing(baseline, criteria):
    """측정값이 없으면 '나빠졌다는 증거 없음'이 아니라 '좋다는 증거 없음'으로 실패 (설계 의도 5)."""
    cand = copy.deepcopy(baseline)
    for r in qwen_rows(cand):
        r["tokens_per_sec"] = None
    assert gate(baseline, cand, criteria)["tokens_per_sec_drop_max_pct"] is False


# ── 3. 비교 가능 여부 (T4~T5) ─────────────────────────────

def _with_config(payload: dict, **overrides) -> dict:
    config = {
        "options": {"temperature": 0.2, "num_predict": 350},
        "repeat_count": 2,
        "system_prompt_sha256": "p",
        "questions_sha256": "q",
        "model_digests": {QWEN: "845dbda0ea48"},
    }
    config.update(overrides)
    payload = copy.deepcopy(payload)
    payload["metadata"]["run_config"] = config
    return payload


def test_missing_question_blocks_comparison(baseline):                  # T5
    cand = copy.deepcopy(baseline)
    cand["results"] = [r for r in cand["results"] if r["question_id"] != "Q10"]
    with pytest.raises(ComparabilityError, match="Q10"):
        check_comparability(baseline, cand, QWEN, allow_config_change=False)


def test_changed_options_block_comparison(baseline):                    # T4
    base = _with_config(baseline)
    cand = _with_config(baseline, options={"temperature": 0.2, "num_predict": 350, "seed": 1})
    with pytest.raises(ComparabilityError, match="options"):
        check_comparability(base, cand, QWEN, allow_config_change=False)


def test_changed_options_allowed_with_flag_leaves_warning(baseline):
    base = _with_config(baseline)
    cand = _with_config(baseline, system_prompt_sha256="changed")
    warnings = check_comparability(base, cand, QWEN, allow_config_change=True)
    assert any("system_prompt_sha256" in w for w in warnings)


def test_changed_model_digest_blocks_comparison(baseline):
    """같은 태그라도 다시 pull 해서 가중치가 바뀌면 다른 모델로 본다."""
    base = _with_config(baseline)
    cand = _with_config(baseline, model_digests={QWEN: "ffffffffffff"})
    with pytest.raises(ComparabilityError, match="model_digest"):
        check_comparability(base, cand, QWEN, allow_config_change=False)


def test_v1_0_log_without_config_only_warns(baseline):
    warnings = check_comparability(baseline, copy.deepcopy(baseline), QWEN, allow_config_change=False)
    assert any("run_config" in w for w in warnings)


# ── 4. 판정 변화 목록 (T6) ────────────────────────────────

def test_verdict_changes_are_listed(baseline):                          # T6
    """1·2회차를 맞바꾸면 v1.0 에서 흔들렸던 Qwen Q08 모듈 판정이 변화로 잡혀야 한다."""
    cand = copy.deepcopy(baseline)
    for r in cand["results"]:
        r["run_index"] = 3 - r["run_index"]
    changes = verdict_changes(formal_rows(baseline, QWEN), formal_rows(cand, QWEN))
    q08 = [c for c in changes if c["question_id"] == "Q08"]
    assert q08 and "모듈" in q08[0]["changes"]


# ── 5. 기준 파일 검증 ─────────────────────────────────────

def test_repository_criteria_file_is_valid(criteria):
    validate_criteria(criteria)   # 예외가 나지 않으면 통과


@pytest.mark.parametrize("broken, message", [
    ({"absolute": {"strict_rate_mn": 95.0}}, "strict_rate_mn"),     # 키 오타
    ({"absolut": {"strict_rate_min": 95.0}}, "absolut"),            # 섹션 오타
    ({"absolute": {"latency_sec_max": "2초"}}, "숫자가 아님"),       # 숫자 아님
])
def test_typo_in_criteria_is_rejected(broken, message):
    """오타가 난 기준은 조용히 빠져서 '검사 안 하고 통과'가 된다 (설계 의도 8)."""
    with pytest.raises(CriteriaError, match=message):
        validate_criteria(broken)


# ── 6. 명령줄 동작과 종료 코드 ────────────────────────────

def test_latest_history_picks_newest_file(tmp_path):
    for stamp in ("20260930_154355", "20261001_090000", "20260901_120000"):
        (tmp_path / f"local_eval_results_{stamp}.json").write_text("{}", encoding="utf-8")
    assert latest_history(tmp_path).name == "local_eval_results_20261001_090000.json"


def test_latest_history_without_files_is_an_error(tmp_path):
    with pytest.raises(ComparabilityError):
        latest_history(tmp_path)


def test_cli_exit_code_pass(baseline, write_json):
    cand = write_json("cand.json", baseline)
    assert cr.main(["--candidate", str(cand), "--no-write"]) == cr.EXIT_PASS


def test_cli_exit_code_fail(baseline, write_json):
    cand = write_json("cand.json", baseline)
    assert cr.main(["--candidate", str(cand), "--model", LLAMA, "--no-write"]) == cr.EXIT_FAIL


def test_cli_exit_code_error_for_missing_file(tmp_path):
    missing = tmp_path / "없는파일.json"
    assert cr.main(["--candidate", str(missing), "--no-write"]) == cr.EXIT_ERROR


def test_cli_exit_code_error_for_broken_criteria(baseline, write_json, tmp_path):
    cand = write_json("cand.json", baseline)
    bad = tmp_path / "bad.toml"
    bad.write_text("[absolute]\nstrict_rate_mn = 95.0\n", encoding="utf-8")
    assert cr.main(["--candidate", str(cand), "--criteria", str(bad), "--no-write"]) == cr.EXIT_ERROR
