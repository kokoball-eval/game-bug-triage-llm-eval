"""selection.py 테스트 — v1.3 개발용 실행 기록(qwen2.5, seed 1)을 복사해 후보 모델과 seed 3개를 만든다."""

import copy
import json
import re
from pathlib import Path

import pytest

from triage_eval.pipeline import gate as g
from triage_eval.pipeline import selection as sel

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data/results/v13/history/v13_dev_20261002_160511.json"   # 최종 구성, qwen2.5:7b seed 1
BASE, CAND = "qwen2.5:7b", "cand:1"
SEEDS = (1, 11, 21)


@pytest.fixture
def crits():
    return sel.load_select_criteria(sel.SELECT_CRITERIA)


def make_log(seed: int, cand_edit=None, cand_latency=None) -> dict:
    """현재 모델 결과를 그대로 두고, 같은 응답을 후보 모델 이름으로 한 벌 더 만든다 (v1.4 실행 기록 형태)."""
    log = json.loads(SOURCE.read_text(encoding="utf-8"))
    cfg = log["metadata"]["run_config"]
    cfg["think"] = False
    cfg["seeds"] = {"1": seed, "2": seed + 1}
    cand = []
    for r in log["results"]:
        c = copy.deepcopy(r)
        c["model"] = CAND
        if cand_latency is not None:
            c["elapsed_sec"] = cand_latency
        cand.append(cand_edit(c) if cand_edit else c)
    log["results"] += cand
    log["metadata"]["models"] = [BASE, CAND]
    return log


def fix_s04b(r):
    """현재 모델이 놓친 Critical(S04b, X-1)을 후보는 맞힌 것으로 만든다."""
    if r["item_id"] == "S04b":
        for f, v in (("우선순위", "Critical"), ("처리", "긴급 사인 요청")):
            r["response_text"] = re.sub(rf"^\[{f}\]:.*$", f"[{f}]: {v}", r["response_text"], flags=re.M)
    return r


def run_sel(tmp_path, logs, crits):
    paths = []
    for n, log in enumerate(logs):
        p = tmp_path / f"run{n}.json"
        p.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")
        paths.append(p)
    crit, gate_crit = crits
    try:
        return sel.run(paths, crit, gate_crit, write=False)
    except g.GateError:  # main() 과 같이 판정 불가는 종료 코드 2
        return 2


def test_criteria_reuse_gate_values_without_latency_increase(crits):
    """설계 의도 1·3 — 회귀 기준은 게이트 파일에서 읽고, 지연 증가율만 뺀다."""
    crit, gate_crit = crits
    gate_file = g.load_criteria(g.CRITERIA)
    assert "latency_increase_max_pct" not in gate_crit["regression"]
    assert gate_crit["absolute"] == gate_file["absolute"]
    assert gate_crit["regression"]["x1_miss_increase_max"] == gate_file["regression"]["x1_miss_increase_max"]
    assert crit["absolute"]["latency_max_sec"] == 10.0


def test_identical_candidate_keeps_current_model(tmp_path, crits):
    """설계 의도 5 — 나빠지지 않았어도 좋아지지 않았으면 바꾸지 않는다 (종료 코드 1)."""
    assert run_sel(tmp_path, [make_log(s) for s in SEEDS], crits) == 1


def test_improved_candidate_is_chosen(tmp_path, crits):
    assert run_sel(tmp_path, [make_log(s, fix_s04b) for s in SEEDS], crits) == 0


def test_improvement_on_one_seed_only_is_not_enough_if_another_seed_fails(tmp_path, crits):
    """설계 의도 4 — 한 seed라도 기준을 못 넘으면 교체 대상이 아니다 (여기서는 지연 절대 기준)."""
    logs = [make_log(1, fix_s04b), make_log(11, fix_s04b), make_log(21, fix_s04b, cand_latency=12.0)]
    assert run_sel(tmp_path, logs, crits) == 1


def test_latency_is_absolute_not_relative(tmp_path, crits):
    """설계 의도 3 — 현재 모델의 3배여도 10초 안이면 지연 기준은 통과한다."""
    assert run_sel(tmp_path, [make_log(s, fix_s04b, cand_latency=5.0) for s in SEEDS], crits) == 0


def test_prompt_change_is_rejected(tmp_path, crits):
    """설계 의도 2 — 모델 비교에서는 프롬프트까지 같아야 한다 (게이트와 다른 점)."""
    logs = [make_log(s) for s in SEEDS]
    logs[2]["metadata"]["run_config"]["system_prompt_sha256"] = "다름"
    assert run_sel(tmp_path, logs, crits) == 2


def test_pre_v14_runs_are_rejected(tmp_path, crits):
    """생각 끄기 설정 기록이 없는 v1.3 실행은 비교하지 않는다."""
    logs = [make_log(s) for s in SEEDS]
    for log in logs:
        del log["metadata"]["run_config"]["think"]
    assert run_sel(tmp_path, logs, crits) == 2


def test_wrong_seed_count_and_duplicates_are_rejected(tmp_path, crits):
    assert run_sel(tmp_path, [make_log(1), make_log(11)], crits) == 2
    assert run_sel(tmp_path, [make_log(1), make_log(1), make_log(21)], crits) == 2


def test_test_split_is_rejected(tmp_path, crits):
    """설계 의도 6"""
    logs = [make_log(s) for s in SEEDS]
    logs[0]["results"][0]["split"] = "test"
    assert run_sel(tmp_path, logs, crits) == 2


def test_unknown_key_in_criteria_is_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text(sel.SELECT_CRITERIA.read_text(encoding="utf-8").replace("latency_max_sec", "latency_max_secs"),
                   encoding="utf-8")
    with pytest.raises(g.GateError):
        sel.load_select_criteria(bad)


def summary(x1b, x1c, pb, pc, lat=3.0, ok=True):
    return {"all_seeds_passed": ok, "x1_base": x1b, "x1_cand": x1c, "pri_base": pb, "pri_cand": pc, "latency_cand": lat}


def test_decide_rules():
    """설계 의도 5·7 — 선택 규칙을 집계값만으로 확인한다."""
    assert sel.decide({"a": summary(6, 6, 120, 120)})[0] is None              # 같음 → 유지
    assert sel.decide({"a": summary(6, 6, 120, 125)})[0] == "a"               # X-1 같고 우선순위 개선
    assert sel.decide({"a": summary(6, 7, 120, 150)})[0] is None              # 우선순위가 늘어도 X-1이 늘면 아님
    assert sel.decide({"a": summary(6, 2, 120, 100, ok=False)})[0] is None    # 기준 미통과
    pick = sel.decide({"a": summary(6, 3, 120, 120, lat=5.0), "b": summary(6, 3, 120, 120, lat=2.0),
                       "c": summary(6, 4, 120, 160)})
    assert pick[0] == "b"                                                     # X-1 → 우선순위 → 지연
