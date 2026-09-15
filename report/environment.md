# 실행 환경 및 자원 점유 실측 (Environment Capture)

> `src/capture_env.py` 자동 생성 · 측정 시각 2026-09-15T12:08:12.900895
> 40회 본 실험 종료 후 동일 모델 태그·동일 양자화 조건에서 수행한 **사후 측정**이며,
> 본 실험의 품질·성능 집계 수치에는 영향을 주지 않습니다. 원본: `data/results/environment.json`

## 1. 시스템 환경

| 항목 | 값 |
| :--- | :--- |
| OS | Windows 11 (AMD64) |
| Python | 3.12.13 |
| Ollama 버전 | ollama version is 0.34.0 |
| Python 패키지 | ollama 0.6.2 · openai 3.13.0 |
| 시스템 총 RAM | 31.4 GB |
| 측정 시점 가용 RAM | 15.8 GB |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU (VRAM 8151 MiB, 드라이버 592.01) |

## 2. 모델별 자원 점유 (디스크 / VRAM / 시스템 RAM 구분)

| 모델 | 디스크 용량 | 총 적재 크기 | VRAM 점유 | 시스템 RAM 점유 | GPU 오프로드 | 실측 context length | 양자화 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `qwen2.5:7b` | 4.68 GB (4.36 GiB) | 4528.1 MiB | **4528.1 MiB** | **0.0 MiB** | 100.0% | 4096 | `Q4_K_M` |
| `llama3.1:8b` | 4.92 GB (4.58 GiB) | 5027.5 MiB | **5027.5 MiB** | **0.0 MiB** | 100.0% | 4096 | `Q4_K_M` |

* **시스템 RAM 점유** = `ollama ps`의 `size` − `size_vram`. 값이 0이면 모델이 전량 GPU에 적재된 것입니다.
* **디스크 용량**은 `ollama list`가 표시하는 10진 GB와 메모리 계산 기준인 GiB를 함께 표기했습니다.
* **실측 context length**는 `ollama ps`가 보고한 실제 적용 값으로, `run_eval.py`에서 `num_ctx`를 지정하지 않아
  Ollama 기본값이 그대로 사용된 결과입니다. 문서에 기재할 Context 설정값은 이 실측치를 따릅니다.

## 3. 실행 경로 검증 (CLI / Python)

발제문 STEP 4는 **CLI 대화 성공과 Python 호출 성공을 각각** 확인하도록 요구합니다.

| 경로 | 확인 방법 | 결과 |
| :--- | :--- | :--- |
| **CLI 경로** | `ollama run qwen2.5:7b "설정 메뉴 텍스트 오타 제보의 심각도를 Blocker/Critical/Major/Minor/Trivial 중 한 단어로만 답하라."` | ✅ 성공 (종료 코드 0) · 응답: `Critical` |
| **Python 경로** | `src/01_ollama_chat.py`, `src/run_eval.py` | ✅ 성공 — 결과가 `data/results/*_verify.json`, `data/results/local_eval_results.json`에 저장됨 |

* CLI 응답 전문은 `data/results/environment.json`의 `cli_path_check` 항목에 보존됩니다.
* 본 실험(40회)은 Python 경로로만 수행했으며, CLI 경로는 실행 가능 여부 확인용입니다.
