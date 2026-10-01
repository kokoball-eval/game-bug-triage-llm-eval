"""벤치마크 실행 전 측정 환경 점검 (v1.2).

2026-09-30 재실행에서 모델 파일(digest)은 그대로인데 Llama의 평균 지연이 +45.6%,
생성 속도가 −32.5% 흔들렸다. 같은 GPU를 쓰는 다른 프로그램(게임 등)이나 전원 상태 같은
측정 환경 차이가 원인으로 보였다(docs/issue_log.md OBS-001).

이 모듈은 run_eval.py 가 모델을 호출하기 전에 환경을 찍어 두고, 측정을 오염시킬 수 있는
상태면 경고한다. 결과는 로그의 metadata.run_config.environment 에 남아
compare_runs.py 가 두 실행의 환경 차이를 함께 보여준다.

점검 항목
---------
    GPU 점유     nvidia-smi 의 사용 중 VRAM. Ollama가 이미 올려 둔 모델 분량은 빼고 본다
    Ollama 적재  실행 전에 이미 올라가 있는 모델 (참고 기록만. 워밍업 로딩 시간에만 영향을 주고,
                 워밍업은 본 통계에서 빠지므로 경고로 치지 않는다)
    전원 연결    노트북 배터리 구동이면 GPU 클럭이 낮아질 수 있음 (Windows 전용)

[설계 의도]
1. 점검 실패는 실험을 막지 않고 기록만 한다. 막고 싶으면 run_eval.py --strict-env.
   "측정할 수 없음"(nvidia-smi 없음 등)과 "문제 있음"을 구분해, 측정 불가는 경고로 치지 않는다.
2. 함수마다 외부 명령·OS 호출을 한 곳에 모아 두고, 판정 로직(evaluate)은 순수 함수로 분리했다.
   CI(리눅스, GPU 없음)에서도 판정 로직을 테스트할 수 있게 하기 위해서다.
"""

import ctypes
import platform
import shutil
import subprocess

# 다른 프로그램이 이만큼 이상 VRAM을 쓰고 있으면 경고 (Windows 바탕화면만으로도 수백 MiB는 쓴다)
OTHER_VRAM_WARN_MIB = 1024


def gpu_used_mib() -> float | None:
    """nvidia-smi 로 현재 사용 중인 VRAM(MiB). 측정할 수 없으면 None."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        values = [float(v) for v in out.stdout.split() if v.strip()]
        return sum(values) if values else None
    except Exception:
        return None


def on_ac_power() -> bool | None:
    """전원 어댑터 연결 여부 (Windows). 판별할 수 없으면 None."""
    if platform.system() != "Windows":
        return None

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    try:
        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None
        return {0: False, 1: True}.get(status.ACLineStatus)
    except Exception:
        return None


def ollama_loaded(client) -> list[dict]:
    """실행 전에 Ollama에 이미 올라가 있는 모델과 VRAM 점유(MiB)."""
    try:
        return [
            {"model": m.get("name") or m.get("model"), "vram_mib": round(m.get("size_vram", 0) / (1024 * 1024), 1)}
            for m in client.ps().get("models", [])
        ]
    except Exception:
        return []


def evaluate(gpu_used: float | None, loaded: list[dict], ac_power: bool | None) -> dict:
    """측정값으로 경고 목록을 만든다. 외부 호출 없는 순수 함수 (설계 의도 2)."""
    warnings, notes = [], []
    ollama_vram = sum(m.get("vram_mib", 0) for m in loaded)
    other_vram = None if gpu_used is None else round(max(gpu_used - ollama_vram, 0.0), 1)

    if other_vram is not None and other_vram >= OTHER_VRAM_WARN_MIB:
        warnings.append(f"다른 프로그램이 VRAM {other_vram:,.0f} MiB를 쓰고 있습니다 "
                        "(게임·영상·브라우저 등). 지연·속도 측정이 오염될 수 있습니다.")
    if loaded:
        names = ", ".join(m["model"] for m in loaded)
        notes.append(f"Ollama에 이미 올라가 있는 모델: {names} (워밍업 로딩 시간만 짧아지며 본 통계에는 영향 없음)")
    if ac_power is False:
        warnings.append("배터리로 구동 중입니다. 전원 어댑터를 연결해야 GPU 성능이 일정합니다.")

    return {
        "gpu_used_mib": gpu_used,
        "ollama_loaded": loaded,
        "other_vram_mib": other_vram,
        "on_ac_power": ac_power,
        "warnings": warnings,
        "notes": notes,
    }


def snapshot(client) -> dict:
    """실행 전 환경을 한 번에 측정하고 판정한다."""
    return evaluate(gpu_used_mib(), ollama_loaded(client), on_ac_power())
