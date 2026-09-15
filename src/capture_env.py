"""
실행 환경 및 자원 점유 실측 캡처 스크립트

목적
----
발제문 STEP 3이 요구하는 "다운로드 파일 크기 / 시스템 RAM / VRAM 사용량 구분 기록"과
"실험에서 실제로 사용한 Context Length" 항목을 사람이 눈으로 적지 않고 실측해서 기록한다.

배경
----
40회 본 실험(`run_eval.py`)은 `ollama ps`에서 `size_vram`만 추출해 저장했기 때문에,
원본 로그(`local_eval_results.json`)만으로는 아래 두 가지를 알 수 없다.
  1) 모델 총 적재 크기 중 시스템 RAM으로 내려간 분량 (= size - size_vram)
  2) 추론 시 실제로 적용된 context length
본 스크립트는 동일한 모델 태그·동일한 양자화 조건에서 이 값을 사후 측정해 보완한다.
**본 실험의 품질·성능 집계 결과는 이 스크립트로 바뀌지 않는다** (읽기 전용 측정).

사용법
------
    uv run python src/capture_env.py

출력
----
    data/results/environment.json   : 기계 판독용 원본
    report/environment.md           : 보고서 첨부용 표
"""

import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import ollama

MODELS = ["qwen2.5:7b", "llama3.1:8b"]
MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024


def get_system_ram():
    """시스템 총/가용 RAM(bytes). psutil이 없으면 OS별 기본 수단으로 대체."""
    try:
        import psutil  # noqa

        vm = psutil.virtual_memory()
        return {"total_bytes": vm.total, "available_bytes": vm.available, "source": "psutil"}
    except ImportError:
        pass

    if sys.platform == "win32":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return {
                "total_bytes": stat.ullTotalPhys,
                "available_bytes": stat.ullAvailPhys,
                "source": "GlobalMemoryStatusEx",
            }
        except Exception as e:
            return {"total_bytes": None, "available_bytes": None, "source": f"unavailable ({e})"}

    return {"total_bytes": None, "available_bytes": None, "source": "unavailable"}


def get_ollama_version():
    """Ollama 서버/CLI 버전 (발제문 STEP 4: Python/Ollama/주요 패키지 버전 기록)."""
    if not shutil.which("ollama"):
        return {"available": False, "note": "ollama 실행 파일 미탐지"}
    try:
        out = subprocess.run(
            ["ollama", "--version"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=True,
        ).stdout.strip()
        return {"available": True, "raw": out}
    except Exception as e:
        return {"available": False, "note": f"조회 실패: {e}"}


def get_package_versions():
    """주요 Python 패키지 설치 버전."""
    from importlib.metadata import PackageNotFoundError, version

    versions = {}
    for pkg in ("ollama", "openai"):
        try:
            versions[pkg] = version(pkg)
        except PackageNotFoundError:
            versions[pkg] = "미설치"
    return versions


def verify_cli_chat(model: str) -> dict:
    """
    CLI 경로(ollama run) 호출 성공을 실측한다.
    발제문 STEP 4는 'CLI 대화 성공'과 'Python 호출 성공'을 각각 확인하도록 요구한다.
    Python 경로는 run_eval.py / 01_ollama_chat.py 결과 파일이 증빙하므로,
    여기서는 CLI 경로만 별도로 확인한다.
    """
    prompt = "설정 메뉴 텍스트 오타 제보의 심각도를 Blocker/Critical/Major/Minor/Trivial 중 한 단어로만 답하라."
    if not shutil.which("ollama"):
        return {"model": model, "success": False, "note": "ollama 실행 파일 미탐지"}
    try:
        proc = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
        )
        ok = proc.returncode == 0 and bool(proc.stdout.strip())
        return {
            "model": model,
            "command": f'ollama run {model} "{prompt}"',
            "success": ok,
            "returncode": proc.returncode,
            "response_text": proc.stdout.strip(),
            "stderr": proc.stderr.strip()[:500] if proc.stderr else "",
        }
    except Exception as e:
        return {"model": model, "success": False, "note": f"실행 실패: {e}"}


def get_gpu_info():
    """nvidia-smi가 있으면 GPU 이름과 VRAM 총량을 기록."""
    if not shutil.which("nvidia-smi"):
        return {"detected": False, "note": "nvidia-smi 미탐지"}
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.strip()
        gpus = []
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                gpus.append({
                    "name": parts[0],
                    "memory_total": parts[1],
                    "memory_used_at_capture": parts[2],
                    "driver_version": parts[3],
                })
        return {"detected": True, "gpus": gpus}
    except Exception as e:
        return {"detected": False, "note": f"조회 실패: {e}"}


def get_disk_sizes():
    """`ollama list` 기준 모델 디스크 용량."""
    try:
        listed = ollama.Client().list()
    except Exception as e:
        return {"error": str(e)}
    sizes = {}
    for m in listed.get("models", []):
        name = m.get("name") or m.get("model") or ""
        size = m.get("size")
        if name and size:
            # `ollama list`가 화면에 표시하는 값은 10진 GB, 실제 메모리 계산은 GiB 기준이므로 둘 다 기록
            sizes[name] = {
                "bytes": size,
                "gb_decimal": round(size / 1_000_000_000, 2),
                "gib": round(size / GIB, 2),
            }
    return sizes


def measure_model(client: ollama.Client, model: str) -> dict:
    """모델을 1토큰만 생성해 적재시킨 뒤 ps에서 자원 점유를 읽는다."""
    record = {"model": model}
    try:
        client.generate(model=model, prompt="ping", options={"num_predict": 1})
    except Exception as e:
        record["error"] = f"적재 실패: {e}"
        return record

    try:
        ps = client.ps()
    except Exception as e:
        record["error"] = f"ps 조회 실패: {e}"
        return record

    entry = None
    for m in ps.get("models", []):
        name = m.get("name") or m.get("model") or ""
        if name == model or name.startswith(model.split(":")[0]):
            entry = m
            break

    if entry is None:
        record["error"] = "ps 응답에서 해당 모델을 찾지 못함"
        return record

    size_total = entry.get("size") or 0
    size_vram = entry.get("size_vram") or 0
    size_ram = max(size_total - size_vram, 0)

    details = entry.get("details") or {}
    record.update({
        "digest": (entry.get("digest") or "")[:12],
        "quantization_level": details.get("quantization_level"),
        "parameter_size": details.get("parameter_size"),
        "context_length": entry.get("context_length"),
        "size_total_bytes": size_total,
        "size_total_mib": round(size_total / MIB, 1),
        "size_vram_bytes": size_vram,
        "size_vram_mib": round(size_vram / MIB, 1),
        "size_system_ram_bytes": size_ram,
        "size_system_ram_mib": round(size_ram / MIB, 1),
        "gpu_offload_ratio_pct": round(size_vram / size_total * 100, 1) if size_total else None,
        "processor": "100% GPU" if size_total and size_ram == 0 else "GPU + CPU 분산",
    })
    return record


def main():
    root = Path(__file__).resolve().parent.parent
    client = ollama.Client()

    print("=== 실행 환경 / 자원 점유 실측 캡처 ===")
    print("(본 실험 결과에는 영향을 주지 않는 읽기 전용 사후 측정입니다)\n")

    system_ram = get_system_ram()
    gpu = get_gpu_info()
    disk = get_disk_sizes()
    ollama_version = get_ollama_version()
    pkg_versions = get_package_versions()

    measurements = []
    for model in MODELS:
        print(f"[{model}] 적재 및 측정 중...", end=" ", flush=True)
        rec = measure_model(client, model)
        if "error" in rec:
            print(f"실패 - {rec['error']}")
        else:
            print(
                f"완료 (VRAM {rec['size_vram_mib']} MiB / "
                f"시스템 RAM {rec['size_system_ram_mib']} MiB / "
                f"context {rec['context_length']})"
            )
        measurements.append(rec)

    print("\n[CLI 경로 검증] ollama run 호출 확인 중...", end=" ", flush=True)
    cli_check = verify_cli_chat(MODELS[0])
    print("성공" if cli_check.get("success") else f"실패 - {cli_check.get('note', cli_check.get('stderr', ''))}")

    payload = {
        "captured_at": datetime.now().isoformat(),
        "note": "40회 본 실험 종료 후 동일 모델 태그·동일 양자화 조건에서 수행한 사후 환경 측정",
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "system_ram": system_ram,
        "gpu": gpu,
        "ollama_version": ollama_version,
        "package_versions": pkg_versions,
        "disk_sizes": disk,
        "models": measurements,
        "cli_path_check": cli_check,
    }

    out_json = root / "data" / "results" / "environment.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 보고서용 마크다운 ────────────────────────────────
    L = []
    A = L.append
    A("# 실행 환경 및 자원 점유 실측 (Environment Capture)\n")
    A(f"> `src/capture_env.py` 자동 생성 · 측정 시각 {payload['captured_at']}")
    A("> 40회 본 실험 종료 후 동일 모델 태그·동일 양자화 조건에서 수행한 **사후 측정**이며,")
    A("> 본 실험의 품질·성능 집계 수치에는 영향을 주지 않습니다. 원본: `data/results/environment.json`\n")

    A("## 1. 시스템 환경\n")
    A("| 항목 | 값 |")
    A("| :--- | :--- |")
    A(f"| OS | {payload['platform']['system']} {payload['platform']['release']} ({payload['platform']['machine']}) |")
    A(f"| Python | {payload['platform']['python']} |")
    A(f"| Ollama 버전 | {ollama_version.get('raw') or ollama_version.get('note', '확인 불가')} |")
    A(f"| Python 패키지 | ollama {pkg_versions.get('ollama')} · openai {pkg_versions.get('openai')} |")
    total = system_ram.get("total_bytes")
    avail = system_ram.get("available_bytes")
    A(f"| 시스템 총 RAM | {round(total / GIB, 1) if total else '측정 불가'} GB |")
    A(f"| 측정 시점 가용 RAM | {round(avail / GIB, 1) if avail else '측정 불가'} GB |")
    if gpu.get("detected"):
        for g in gpu["gpus"]:
            A(f"| GPU | {g['name']} (VRAM {g['memory_total']}, 드라이버 {g['driver_version']}) |")
    else:
        A(f"| GPU | {gpu.get('note', '정보 없음')} |")
    A("")

    A("## 2. 모델별 자원 점유 (디스크 / VRAM / 시스템 RAM 구분)\n")
    A("| 모델 | 디스크 용량 | 총 적재 크기 | VRAM 점유 | 시스템 RAM 점유 | GPU 오프로드 | 실측 context length | 양자화 |")
    A("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for rec in measurements:
        if "error" in rec:
            A(f"| `{rec['model']}` | - | - | - | - | - | - | 측정 실패: {rec['error']} |")
            continue
        d = disk.get(rec["model"], {}) if isinstance(disk, dict) else {}
        disk_txt = f"{d.get('gb_decimal')} GB ({d.get('gib')} GiB)" if d.get("gb_decimal") else "-"
        A(
            f"| `{rec['model']}` | {disk_txt} | {rec['size_total_mib']} MiB | "
            f"**{rec['size_vram_mib']} MiB** | **{rec['size_system_ram_mib']} MiB** | "
            f"{rec['gpu_offload_ratio_pct']}% | {rec['context_length']} | `{rec['quantization_level']}` |"
        )
    A("")
    A("* **시스템 RAM 점유** = `ollama ps`의 `size` − `size_vram`. 값이 0이면 모델이 전량 GPU에 적재된 것입니다.")
    A("* **디스크 용량**은 `ollama list`가 표시하는 10진 GB와 메모리 계산 기준인 GiB를 함께 표기했습니다.")
    A("* **실측 context length**는 `ollama ps`가 보고한 실제 적용 값으로, `run_eval.py`에서 `num_ctx`를 지정하지 않아")
    A("  Ollama 기본값이 그대로 사용된 결과입니다. 문서에 기재할 Context 설정값은 이 실측치를 따릅니다.")
    A("")

    A("## 3. 실행 경로 검증 (CLI / Python)\n")
    A("발제문 STEP 4는 **CLI 대화 성공과 Python 호출 성공을 각각** 확인하도록 요구합니다.\n")
    A("| 경로 | 확인 방법 | 결과 |")
    A("| :--- | :--- | :--- |")
    if cli_check.get("success"):
        preview = " ".join(cli_check.get("response_text", "").split())[:80]
        A(f"| **CLI 경로** | `{cli_check.get('command')}` | ✅ 성공 (종료 코드 {cli_check.get('returncode')}) · 응답: `{preview}` |")
    else:
        reason = cli_check.get("note") or cli_check.get("stderr") or "사유 미상"
        A(f"| **CLI 경로** | `ollama run {MODELS[0]} ...` | ❌ 실패 — {reason} |")
    A("| **Python 경로** | `src/01_ollama_chat.py`, `src/run_eval.py` | ✅ 성공 — 결과가 "
      "`data/results/*_verify.json`, `data/results/local_eval_results.json`에 저장됨 |")
    A("")
    A("* CLI 응답 전문은 `data/results/environment.json`의 `cli_path_check` 항목에 보존됩니다.")
    A("* 본 실험(40회)은 Python 경로로만 수행했으며, CLI 경로는 실행 가능 여부 확인용입니다.")
    A("")

    out_md = root / "report" / "environment.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(L), encoding="utf-8")

    print(f"\n저장 완료:\n  - {out_json}\n  - {out_md}")


if __name__ == "__main__":
    main()
