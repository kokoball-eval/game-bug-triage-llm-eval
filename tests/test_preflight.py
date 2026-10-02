"""preflight.py 측정 환경 점검 테스트.

외부 명령(nvidia-smi)과 OS 호출(전원 상태)은 CI에서 쓸 수 없으므로,
측정값을 받아 경고를 만드는 순수 함수 evaluate() 만 테스트한다 (preflight.py 설계 의도 2).
"""

import pytest

from triage_eval.common.preflight import OTHER_VRAM_WARN_MIB, evaluate


def test_clean_environment_has_no_warning():
    env = evaluate(gpu_used=350.0, loaded=[], ac_power=True)
    assert env["warnings"] == []
    assert env["other_vram_mib"] == 350.0


def test_other_program_using_gpu_is_warned():
    """9/30 재실행처럼 게임 등이 VRAM을 쓰고 있으면 경고 (docs/issue_log.md OBS-001)."""
    env = evaluate(gpu_used=OTHER_VRAM_WARN_MIB + 500, loaded=[], ac_power=True)
    assert any("VRAM" in w for w in env["warnings"])


def test_ollama_own_models_are_not_counted_as_other_program():
    """Ollama가 올려 둔 모델 분량은 '다른 프로그램'으로 치지 않는다.
    적재 사실은 참고(notes)로만 남긴다 — 워밍업은 본 통계에서 빠지므로 측정 오염이 아니다."""
    env = evaluate(gpu_used=4900.0, loaded=[{"model": "qwen2.5:7b", "vram_mib": 4528.1}], ac_power=True)
    assert env["other_vram_mib"] == pytest.approx(371.9)
    assert env["warnings"] == []
    assert any("qwen2.5:7b" in n for n in env["notes"])


def test_battery_power_is_warned():
    env = evaluate(gpu_used=300.0, loaded=[], ac_power=False)
    assert any("배터리" in w for w in env["warnings"])


def test_unmeasurable_values_are_not_warnings():
    """측정할 수 없음(None)은 '문제 있음'이 아니다 (preflight.py 설계 의도 1)."""
    env = evaluate(gpu_used=None, loaded=[], ac_power=None)
    assert env["warnings"] == []
    assert env["other_vram_mib"] is None
