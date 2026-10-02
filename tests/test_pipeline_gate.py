"""v1.3 회귀 게이트 (gate.py) 테스트 — 고정 기준선 실행 기록을 고쳐 후보를 만든다."""

import copy
import json
import re
from pathlib import Path

import pytest

from triage_eval.pipeline import gate as g

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "data/results/v13/baseline/v13_dev_seed1_baseline.json"
QWEN = ["qwen2.5:7b"]


@pytest.fixture
def crit():
    return g.load_criteria(g.CRITERIA)


def base():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def set_field(log, item_id, field, value, runs=(1, 2), model="qwen2.5:7b"):
    for r in log["results"]:
        if r["model"] == model and r["item_id"] == item_id and r["run_index"] in runs:
            r["response_text"] = re.sub(rf"^\[{re.escape(field)}\]:.*$", f"[{field}]: {value}",
                                        r["response_text"], flags=re.M)
    return log


def gate(tmp_path, cand, crit, models=QWEN):
    p = tmp_path / "cand.json"
    p.write_text(json.dumps(cand, ensure_ascii=False), encoding="utf-8")
    return g.run(BASELINE, p, models, crit, write=False)


def test_identical_run_passes(tmp_path, crit):
    """기준선과 같은 실행은 회귀 기준을 모두 통과한다. 허용 값 위반(R6) 절대 기준은 아래 테스트에서 따로 본다."""
    relaxed = copy.deepcopy(crit)
    relaxed["absolute"].pop("enum_violation_max")
    assert gate(tmp_path, base(), relaxed) == 0


def test_baseline_itself_fails_enum_floor(crit):
    """기준선에는 허용 값 위반이 7건 있다. R6 절대 기준은 기준선 대비가 아니라 0건을 요구한다."""
    checks = g.judge(*_counts_and_changes(base()), crit)
    row = next(c for c in checks if c["name"] == "허용 값 위반(R6)")
    assert row["candidate"] == 7 and not row["passed"]


def test_mu_gwan_jung_fails_enum_floor(tmp_path, crit):
    """'무관 중'처럼 허용 값 밖인 분류가 최종 출력에 1건이라도 남으면 FAIL."""
    relaxed_base = base()
    checks = g.judge(*_counts_and_changes(set_field(relaxed_base, "A01", "분류", "무관 중", runs=(1,))), crit)
    assert not _passed(checks, "허용 값 위반(R6)")


def test_criteria_file_has_strict_tiers(crit):
    drop = crit["regression"]["field_drop_max_responses"]
    assert drop["처리"] == 0 and drop["분류"] == 0 and drop["우선순위"] == 1 and drop["모듈"] == 3


def test_one_wrong_action_fails(tmp_path, crit):
    """처리 정답률은 1응답만 나빠져도 FAIL (허용 0)."""
    cand = set_field(base(), "B01", "처리", "개발 배정", runs=(1,))  # 기준선 정답 → 오답
    assert gate(tmp_path, cand, crit) == 1


def test_x1_increase_fails(tmp_path, crit):
    cand = set_field(base(), "B03", "처리", "등록(재현 대기)", runs=(1,))  # Critical 문항
    b = g.counts(g.score_log(base(), "qwen2.5:7b", _items()))
    c = g.counts(g.score_log(cand, "qwen2.5:7b", _items()))
    assert c["x1"] == b["x1"] + 1
    assert gate(tmp_path, cand, crit) == 1


def test_priority_allows_one_but_not_two(tmp_path, crit):
    one = set_field(base(), "B01", "우선순위", "Major", runs=(1,))
    two = set_field(base(), "B01", "우선순위", "Major", runs=(1, 2))
    r1 = g.judge(*_counts_and_changes(one), crit)
    r2 = g.judge(*_counts_and_changes(two), crit)
    assert _passed(r1, "우선순위 정답(응답 수)") and not _passed(r2, "우선순위 정답(응답 수)")


def test_swap_with_same_rate_is_caught_by_item_regression(tmp_path, crit):
    """정답률이 그대로여도 맞히던 문항 2개(4응답)가 틀리게 바뀌면 FAIL."""
    cand = base()
    rows = g.score_log(cand, "qwen2.5:7b", _items())
    right = sorted({k[0] for k, r in rows.items() if r["fields"]["분류"]["ok"]
                    and all(rows[(k[0], i)]["fields"]["분류"]["ok"] for i in (1, 2))})[:2]
    wrong = sorted({k[0] for k, r in rows.items() if not r["fields"]["분류"]["ok"]
                    and not any(rows[(k[0], i)]["fields"]["분류"]["ok"] for i in (1, 2))})[:2]
    for i in right:
        set_field(cand, i, "분류", "무관")
    for i in wrong:
        set_field(cand, i, "분류", _items()[i]["labels"]["분류"][0])
    checks = g.judge(*_counts_and_changes(cand), crit)
    assert _passed(checks, "분류 정답(응답 수)")              # 정답률은 그대로
    assert not _passed(checks, "분류 문항 단위 회귀(응답 수)")  # 하지만 4응답이 새로 틀림


def test_test_split_is_refused(tmp_path, crit):
    cand = base()
    cand["results"][0]["split"] = "test"
    with pytest.raises(g.GateError):
        gate(tmp_path, cand, crit)


def test_different_seed_is_refused(tmp_path, crit):
    cand = base()
    cand["metadata"]["run_config"]["seeds"] = {"1": 7, "2": 8}
    with pytest.raises(g.GateError):
        gate(tmp_path, cand, crit)


def test_prompt_change_is_allowed_and_noted(crit):
    cand = base()
    cand["metadata"]["run_config"]["system_prompt_sha256"] = "changed"
    assert g.check_comparable(base(), cand, QWEN) == ["프롬프트 변경됨 (이 게이트가 판정하려는 변경)"]


def test_unknown_criteria_key_is_refused(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(g.CRITERIA.read_text(encoding="utf-8").replace('"처리" = 0 ', '"처리_" = 0 ', 1), encoding="utf-8")
    with pytest.raises(g.GateError):
        g.load_criteria(p)


def test_main_exit_codes(tmp_path):
    assert g.main(["--candidate", str(tmp_path / "없음.json")]) == 2


# ── 도우미 ─────────────────────────────────────────────────
def _items():
    return {i["id"]: i for i in json.loads(g.DATASET.read_text(encoding="utf-8"))["items"]}


def _counts_and_changes(cand):
    items = _items()
    b, c = g.score_log(base(), "qwen2.5:7b", items), g.score_log(cand, "qwen2.5:7b", items)
    return g.counts(b), g.counts(c), g.item_changes(b, c)


def _passed(checks, name):
    return next(c for c in checks if c["name"] == name)["passed"]


def test_language_drift_fails_absolute_criterion(tmp_path, crit):
    """응답 1건이라도 다른 언어로 넘어가면 절대 기준 위반 (ISSUE-007)."""
    cand = base()
    for r in cand["results"]:
        if r["model"] == "qwen2.5:7b" and r["item_id"] == "B01" and r["run_index"] == 1:
            r["response_text"] = r["response_text"].replace("[요약]:", "[요약]: 游戏崩溃", 1)
    checks = g.judge(*_counts_and_changes(cand), crit)
    assert not _passed(checks, "출력 언어 위반(R7)")
