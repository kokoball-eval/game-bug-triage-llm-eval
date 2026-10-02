"""run_eval.py seed 고정 모드 테스트 (모델은 호출하지 않는다)."""

from triage_eval.bench_v1.run_eval import OPTIONS, options_for_run


def test_no_seed_keeps_v1_0_options():
    """seed 를 주지 않으면 v1.0 과 같은 옵션이어야 기존 로그와 비교할 수 있다."""
    assert options_for_run(None, 1) == OPTIONS
    assert "seed" not in options_for_run(None, 2)


def test_each_run_gets_its_own_fixed_seed():
    """1회차 seed=N, 2회차 seed=N+1 — 회차 간 변동은 관찰하면서 재실행 재현성은 확보 (설계 의도 9)."""
    assert options_for_run(1, 1)["seed"] == 1
    assert options_for_run(1, 2)["seed"] == 2
    assert options_for_run(10, 2)["seed"] == 11


def test_base_options_are_not_mutated():
    options_for_run(1, 1)
    assert "seed" not in OPTIONS
