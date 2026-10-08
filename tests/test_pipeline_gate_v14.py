"""채택 구성 회귀 게이트(gate_v14.py, triage-gate --dataset v14) 테스트.

- 저장소에 커밋된 v1.4 실제 실행 기록으로 판정 결과를 고정한다 (모델 호출 없음).
- 가짜 모델로 실행 → 게이트까지 이어지는 전 과정을 확인한다.
"""

import copy
import json
from pathlib import Path

import pytest

from test_pipeline_methods import NO_ALL, FakeClient, run_fake
from triage_eval.pipeline import compare as cmp
from triage_eval.pipeline import gate as g
from triage_eval.pipeline import gate_v14 as gv

ROOT = Path(__file__).resolve().parent.parent
H = ROOT / "data/results/v14/history"
EXP_A_M2 = [H / "v14_dev_m2_20261004_204929.json", H / "v14_dev_m2_20261004_210209.json",
            H / "v14_dev_m2_20261004_211450.json"]
EXP_B = [H / "v14_dev_m2_20261004_214913.json", H / "v14_dev_m2_20261004_222158.json",
         H / "v14_dev_m2_20261004_223945.json"]   # qwen2.5:7b + gemma4:12b, 방법 M2
M0 = [H / "v14_dev_m0_20261004_204024.json", H / "v14_dev_m0_20261004_205305.json",
      H / "v14_dev_m0_20261004_210549.json"]
FINAL = H / "v14_final_m2_20261004_224554.json"
SEEDS = (1, 11, 21)


@pytest.fixture
def crit():
    return gv.load_criteria(gv.CRITERIA)


def write(tmp_path: Path, name: str, log: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")
    return p


# ── 기준 파일과 기준선 ───────────────────────────────────────

def test_criteria_follow_method_selection(crit):
    """기준 값은 v1.4 방법 선택 기준과 같고, 지연 증가율 20%(v1.3 게이트와 같은 값)만 더했다."""
    sel = cmp.load_criteria(cmp.CRITERIA)
    assert crit["absolute"] == sel["absolute"]
    assert crit["relative_to_baseline"] == sel["relative_to_baseline"]
    assert {k: v for k, v in crit["regression"].items() if k != "latency_increase_max_pct"} == sel["regression"]
    assert crit["regression"]["latency_increase_max_pct"] == g.load_criteria(g.CRITERIA)["regression"]["latency_increase_max_pct"]
    assert crit["meta"]["seeds"] == [1, 11, 21] and crit["meta"]["split"] == "dev"


def test_baseline_is_copy_of_experiment_a_m2(crit):
    """고정 기준선은 M2 채택의 근거가 된 실험 A 실행 기록과 내용이 같다 (줄바꿈 방식과 무관하게 비교)."""
    for path, src in zip(crit["meta"]["baseline"], EXP_A_M2):
        assert g.load_log(ROOT / path) == g.load_log(src)


def test_unknown_section_is_rejected(tmp_path):
    bad = tmp_path / "c.toml"
    bad.write_text(gv.CRITERIA.read_text(encoding="utf-8") + "\n[absolute2]\nx = 1\n", encoding="utf-8")
    with pytest.raises(g.GateError):
        gv.load_criteria(bad)


def test_unknown_field_is_rejected(tmp_path):
    """칸 이름 오타로 기준이 조용히 빠진 채 PASS가 나지 않게 한다 (v1.1.1 ISSUE-003)."""
    bad = tmp_path / "c.toml"
    bad.write_text(gv.CRITERIA.read_text(encoding="utf-8").replace('"처리" = 0', '"처리칸" = 0', 1), encoding="utf-8")
    with pytest.raises(g.GateError):
        gv.load_criteria(bad)


def test_missing_key_is_rejected(tmp_path):
    bad = tmp_path / "c.toml"
    bad.write_text(gv.CRITERIA.read_text(encoding="utf-8").replace("latency_max_sec = 10.0", ""), encoding="utf-8")
    with pytest.raises(g.GateError):
        gv.load_criteria(bad)


# ── 실제 실행 기록으로 고정한 판정 ───────────────────────────

def test_reproduced_run_passes_with_no_item_change(crit):
    """실험 B의 qwen2.5:7b + M2는 실험 A와 seed마다 같은 응답이었다(OBS-004) → PASS, 문항 단위 변화 0."""
    assert gv.run(EXP_B, crit, write=False) == 0
    base = gv.by_seed([(p, g.load_log(p)) for p in EXP_A_M2], "기준선", crit)
    cand = gv.by_seed([(p, g.load_log(p)) for p in EXP_B], "후보", crit)
    items = {i["id"]: i for i in json.loads(gv.DATASET.read_text(encoding="utf-8"))["items"]}
    per_seed = [cmp.compare_seed(base[s][1], cand[s][1], "m2/qwen2.5:7b", "m2/qwen2.5:7b", items, gv.judge_criteria(crit))
                for s in SEEDS]
    assert all(t == {"regressed": 0, "fixed": 0} for t in gv.change_totals(per_seed).values())


def test_previous_method_m0_fails_on_x1(crit):
    """체크리스트를 뺀 M0으로 돌아가면 Critical 누락이 늘어 FAIL (방법 변경은 notes에 남는다)."""
    assert gv.run(M0, crit, write=False) == 1


def test_slower_candidate_fails_on_latency_increase(tmp_path, crit):
    """설계 의도 4 — 응답이 같아도 평균 지연이 20%를 넘게 늘면 FAIL."""
    paths = []
    for s, p in zip(SEEDS, EXP_A_M2):
        log = g.load_log(p)
        for r in log["results"]:
            r["elapsed_sec"] = round(r["elapsed_sec"] * 1.3, 3)
        paths.append(write(tmp_path, f"slow{s}.json", log))
    assert gv.run(paths, crit, write=False) == 1


# ── 판정 거부 (종료 코드 2) ──────────────────────────────────

def test_missing_seed_is_refused(crit):
    with pytest.raises(g.GateError, match="seed 구성"):
        gv.run(EXP_B[:2], crit, write=False)


def test_final_split_run_is_refused(crit):
    with pytest.raises(g.GateError, match="개발용이 아닌"):
        gv.run([FINAL] + EXP_B[1:], crit, write=False)


def test_v13_run_is_refused(crit):
    v13 = ROOT / "data/results/v13/baseline/v13_dev_seed1_baseline.json"
    with pytest.raises(g.GateError, match="v1.4 평가셋"):
        gv.run([v13] + EXP_B[1:], crit, write=False)


def test_candidates_with_different_configs_are_refused(crit):
    """seed마다 다른 구성(M0 seed 1 + M2 seed 11·21)이면 무엇을 판정했는지 알 수 없다."""
    with pytest.raises(g.GateError, match="후보 실행끼리"):
        gv.run([M0[0]] + EXP_B[1:], crit, write=False)


def test_different_model_digest_is_refused(tmp_path, crit):
    log = g.load_log(EXP_B[0])
    log["metadata"]["run_config"]["model_digests"]["qwen2.5:7b"] = "다른 digest"
    with pytest.raises(g.GateError, match="digest"):
        gv.run([write(tmp_path, "d.json", log)] + EXP_B[1:], crit, write=False)


def test_stored_runs_have_no_mid_run_reload(crit):
    """기준선·실험 B 실행에는 실행 도중 다시 로드된 응답이 없다 (설계 의도 7의 전제)."""
    for p in EXP_A_M2 + EXP_B:
        assert all((r.get("load_duration_sec") or 0) <= gv.RELOAD_SEC for r in g.load_log(p)["results"])


def test_mid_run_reload_is_refused(tmp_path, crit):
    """설계 의도 7 (OBS-005) — 실행 도중 모델이 다시 로드된 후보는 FAIL이 아니라 판정 불가."""
    log = g.load_log(EXP_B[1])
    hit = next(r for r in log["results"] if r["model"] == "qwen2.5:7b" and r["run_index"] == 2 and r["item_id"] == "A20")
    hit["load_duration_sec"] = 16.438
    with pytest.raises(g.GateError, match="측정 환경 오염"):
        gv.run([EXP_B[0], write(tmp_path, "reload.json", log), EXP_B[2]], crit, write=False)


def test_cli_dispatch(tmp_path):
    """triage-gate --dataset v14 는 게이트 v14로, 기본값은 v1.3 게이트 그대로 (gate.py 설계 의도 7)."""
    assert g.main(["--dataset", "v14", "--candidate", str(EXP_B[0])]) == 2          # seed 누락
    assert g.main(["--dataset", "v14"]) == 2                                        # 후보 없음
    assert g.main(["--candidate", str(EXP_B[0]), "--candidate", str(EXP_B[1])]) == 2  # v1.3 게이트는 1개만


# ── 가짜 모델로 실행 → 게이트 ────────────────────────────────

def fake_crit(crit: dict) -> dict:
    c = copy.deepcopy(crit)
    c["meta"]["target_model"] = "fake"
    return c


def fake_runs(monkeypatch, tmp_path, factory=FakeClient):
    return [run_fake(monkeypatch, tmp_path, "m2", s, factory()) for s in SEEDS]


def test_fake_pipeline_identical_runs_pass(monkeypatch, tmp_path, crit):
    base, cand = fake_runs(monkeypatch, tmp_path), fake_runs(monkeypatch, tmp_path)
    assert gv.run(cand, fake_crit(crit), base_paths=base, write=False) == 0


def test_fake_pipeline_missed_critical_fails(monkeypatch, tmp_path, crit):
    """후보가 Critical 한 건(S04b)을 놓치면 체크리스트가 올리지 못하는 한 FAIL."""
    base = fake_runs(monkeypatch, tmp_path)
    miss = {"S04b": {"우선순위": "Major", "처리": "등록(재현 대기)"}}
    cand = fake_runs(monkeypatch, tmp_path, lambda: FakeClient(override=miss, answers=NO_ALL))
    assert gv.run(cand, fake_crit(crit), base_paths=base, write=False) == 1
