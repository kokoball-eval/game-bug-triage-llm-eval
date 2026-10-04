# Game Bug Triage LLM Eval

> **게임 버그 리포트 1차 트리아지를 LLM에게 맡겨도 되는지, 평가와 회귀 테스트로 계속 검증하는 LLM 평가 체계**
>
> 로컬 LLM 트리아지 파이프라인(Ollama) + 이를 검증하는 현업 기반 평가셋 · 회귀 게이트 · 환각 자동 탐지 · pytest/GitHub Actions CI

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/badge/uv-Fast%20Packaging-DE5FE9?logo=astral)](https://github.com/astral-sh/uv)
[![Inference Engine: Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-000000?logo=ollama)](https://ollama.ai/)
[![tests](https://github.com/kokoball-eval/game-bug-triage-llm-eval/actions/workflows/tests.yml/badge.svg)](https://github.com/kokoball-eval/game-bug-triage-llm-eval/actions/workflows/tests.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

> **30초 요약**
> * **선정**: `qwen2.5:7b` (Qwen2.5-7B-Instruct, Q4_K_M) — 품질 81점 / 포맷 엄격 준수 100% / 평균 1.390초
> * **탈락**: `llama3.1:8b` (77점) — 속도와 단서 보존은 앞섰으나, 단문 리포트에서 **없는 결함과 PC 사양을 날조**
> * **판단 기준**: 속도가 아니라 **데이터 무결성**. 소극적 응답은 룰로 고치지만 환각은 버그 트래커를 오염시킵니다
> * **검증 방식**: 로컬 40회 + Cloud 대조 5회, 총 45회. 문서의 모든 수치는 `src/` 스크립트가 원본 로그에서 재계산합니다

## 목차

| 절 | 내용 | 이런 분께 |
| :--- | :--- | :--- |
| [1. 문제와 접근](#1-문제와-접근) | 왜 로컬 LLM인가, 후보를 어떻게 골랐나 | 배경이 궁금한 분 |
| [2. 결론 — 선정 모델과 근거](#2-결론--선정-모델과-근거) | 4대 의사결정 축, 1~4일차 여정 | **결론만 필요한 분** |
| [3. 벤치마크 결과](#3-벤치마크-결과) | 제원·성능·품질 표, 환각 사례 원문 | 수치를 보실 분 |
| [4. 실행 및 재현](#4-실행-및-재현) | 설치, 실험 실행, 수치 재검증 | 직접 돌려보실 분 |
| [5. 저장소 구조와 상세 보고서](#5-저장소-구조와-상세-보고서) | 보고서 4종, 디렉터리 구성 | 깊이 파보실 분 |
| [6. 프로덕션 도입 로드맵과 한계](#6-프로덕션-도입-로드맵과-한계) | 3대 가드레일, 실험의 한계 | 실무 적용을 검토할 분 |
| [7. 고도화 로드맵](#7-고도화-로드맵) | 무인 트리아지 파이프라인까지의 최종 목표·지표·버전별 계획 | 앞으로의 방향이 궁금한 분 |

---

## 1. 문제와 접근

라이브 서비스 게임에 인입되는 버그 리포트는 하루 수백~수천 건입니다.

대다수가 단문·모호한 표현이거나 복합 결함이 섞여 있어, 담당 QA 엔지니어의 1차 분류(Triage) 단계에서 병목이 생깁니다.

이 작업을 LLM에 맡기려 할 때 걸리는 제약이 하나 있습니다.
**게임 버그 리포트에는 유저 계정 정보와 미출시 콘텐츠가 포함되어 외부 API로 내보낼 수 없습니다.**
이에 따라서 사내 폐쇄망에서 동작하는 로컬 모델이어야 합니다.

본 프로젝트는 가상 게임 "**Aether Raid**"의 리포트 인입 파이프라인을 상정하고,
8GB VRAM 노트북에서 구동 가능한 경량 로컬 LLM 2종(`qwen2.5:7b`, `llama3.1:8b`)의 실무 트리아지 성능을 비교·검증했습니다.
상용 클라우드 모델(`gpt-5.6-luna`)은 로컬 모델의 성능 상한선을 재는 기준선으로만 사용했습니다.

### 후보 모델 선정 기준

먼저 Use Case가 요구하는 **4가지 필수 조건**을 정리하고, 이를 기준으로 후보군을 좁혔습니다.

| 조건 | 왜 필요한가 |
| :--- | :--- |
| **로컬 구동 가능** | 유저 계정·미출시 콘텐츠가 포함되어 외부 API 전송이 불가. Ollama로 내려받아 폐쇄망에서 실행되어야 함 |
| **8GB VRAM 단일 GPU 적재** | 별도 추론 서버 없이 QA 담당자 노트북에서 운용. Q4 양자화 기준 7B~8B급이 상한 |
| **한국어 처리** | 인입되는 버그 리포트 원문이 한국어. 지시를 따르는 Instruct 튜닝 버전이어야 함 |
| **상업적 이용 가능성** | 사내 서비스 적용이 전제이므로 라이선스 조건을 사전 확인 |

조건을 만족하는 여러 후보 가운데 **성격이 대비되는 2종**을 최종 선정했습니다.

* **Llama-3.1-8B-Instruct** — 오픈 LLM에서 가장 널리 쓰이는 기준선. "일반적으로 무난한 선택"이 이 Use Case에서도 통하는지 확인하는 대조군
* **Qwen2.5-7B-Instruct** — 한국어를 포함한 다국어 지원과 Apache 2.0 라이선스를 앞세운 대안. 기준선을 넘어설 수 있는지 검증하는 도전군

두 모델은 파라미터 규모(8.03B vs 7.61B)와 양자화(`Q4_K_M`)가 비슷합니다. **모델 자체의 차이 외 변수를 통제한 상태로 비교**할 수 있다는 점도 이 조합을 고른 이유입니다.

> **선정 과정과 한계** — 후보군은 요구 조건을 정리한 뒤 LLM 도구의 제안을 출발점으로 추렸고, 최종 2종의 제원·라이선스·컨텍스트는 Model Card 원문으로 직접 확인했습니다. 다만 조건을 만족할 수 있는 다른 모델까지 폭넓게 탐색하지는 않았습니다. 5일 일정 안에서 후보 수보다 비교의 깊이를 우선했고, 후보 범위 확대는 후속 과제로 남깁니다.

* **수행 형태**: 1인 단독 프로젝트 (환경 구성, 벤치마크 자동화, 정량/정성 평가 전 과정)
* **실행 환경**: Windows 11 (AMD64), NVIDIA GeForce RTX 5060 Laptop GPU (VRAM 8,151 MiB), 시스템 RAM 31.4 GB, Ollama 0.34.0, Python 3.12.13 (`uv`) — 실측 근거: [`report/environment.md`](report/environment.md)

---

## 2. 결론 — 선정 모델과 근거

### 🏆 Qwen2.5-7B-Instruct (`qwen2.5:7b`, Q4_K_M)

| # | 의사결정 축 | 근거 |
| :---: | :--- | :--- |
| 1 | **데이터 무결성** (결정적 요인) | 단문 리포트에서 없는 결함과 기기 사양을 지어내지 않아 버그 트래커 오염을 차단 |
| 2 | **규격 준수율 100%** | 가드레일 주입 후 20회 전수에서 사족 없이 5개 필드만 출력 → Jira 파싱 에러 0건 |
| 3 | **처리 효율과 자원 마진** | 평균 응답 1.390초로 Llama보다 23% 빠름. VRAM도 499 MiB 적게 점유 |
| 4 | **비즈니스 라이선스** | Apache 2.0 — 사내 폐쇄망 상업 배포와 수정·재배포에 제약 없음 |

> 3번 VRAM 차이는 본 장비에서 당락 조건이 아니었습니다.
> 두 모델 모두 시스템 RAM 오프로드 없이 100% GPU에 적재됐습니다. 컨텍스트 확장·저사양 이식 시의 여유분으로 해석해야 합니다.

### 📌 의사결정 여정 (1~4일차)

| 일차 | 한 일 | 결과 |
| :---: | :--- | :--- |
| **1일차** | 단일 호출 스모크 테스트 | Llama가 고유명사 보존·스키마 준수에서 우세 → *"서두 사족만 가드레일로 잡으면 Llama가 승자"* 가설 수립 |
| **2일차** | 40회 본 실험 | 엣지 케이스(Q08 단문)에서 **Llama의 치명적 환각 발견** → 채택 모델을 Qwen2.5로 선회 |
| **3일차** | Cloud 대조 검증 | 7B 로컬 모델의 한계 2가지 실측 → 3대 프로덕션 가드레일의 기술적 당위성 확보 |
| **4일차** | 가드레일 재실험 | Qwen2.5에 Few-Shot 1건 주입 → 단문 대응 소극성 교정을 기계 채점 4항목 전수 통과로 검증 |

**최종 판단**: *"소극성은 룰과 퓨샷으로 잡을 수 있지만, 날조는 파이프라인을 무너뜨린다."*

> 선정 사유와 배포 계획의 전문은 [`report/final_selection.md`](report/final_selection.md)에 있습니다.

---

## 3. 벤치마크 결과

### 1) 비교 대상 모델 제원

| 구분 | Qwen2.5-7B-Instruct (최종 선정) | Llama-3.1-8B-Instruct (비교 대조) |
| :--- | :--- | :--- |
| **Ollama 태그** | `qwen2.5:7b` | `llama3.1:8b` |
| **파라미터 / 양자화** | 7.61B / `Q4_K_M` | 8.03B / `Q4_K_M` |
| **디스크 용량** | 4.68 GB (4.36 GiB) | 4.92 GB (4.58 GiB) |
| **네이티브 Context** | 32,768 토큰 (YaRN 적용 시 131,072) | 128,000 토큰 |
| **한국어 공식 지원** | 지원 | 공식 지원 8개 언어에 **미포함** |
| **라이선스** | **Apache 2.0** — 상업적 이용·수정·배포 제약 없음 | **Llama 3.1 Community** — MAU 7억 초과 시 별도 계약, 명명 규칙 조건 |

> 실측 context(4,096) · VRAM/시스템 RAM 구분 · 생성 하이퍼파라미터를 포함한 전체 제원표는
> [`report/model_comparison.md`](report/model_comparison.md) §1-2를 참조하세요.

### 2) 하드웨어 및 런타임 성능 요약 ($N=45$)

| 지표 항목 | Qwen2.5-7B (Local, 최종 선정) | Llama-3.1-8B (Local, 비교 대조) | gpt-5.6-luna (Cloud 참조군) |
| :--- | :---: | :---: | :---: |
| **표본 수 ($n$)** | 20 (10문항 × 2회) | 20 (10문항 × 2회) | 5 (사전 지정 공통 문항) |
| **호출 성공률** | **100% (20/20)** | **100% (20/20)** | **100% (5/5)** |
| **포맷 준수율** (엄격 / 파서 호환) | **100% / 100% (20/20)** | 5% / 100% (1/20 · 20/20) | **100% / 100% (5/5)** |
| **평균 응답 지연 (Latency)** | **1.390초** | 1.809초 | 4.079초 (Network RTT 포함) |
| **평균 생성 토큰 속도** | 57.68 tokens/s | **66.56 tokens/s** | N/A (Serverless API) |
| **평균 생성 토큰 수** | **76.4 tokens (핵심 압축)** | 117.6 tokens (다변 서술) | 233.4 tokens (상세 가이드) |
| **VRAM 점유량** | **4,528.1 MiB (~4.42 GB)** | 5,027.5 MiB (~4.91 GB) | 0 MiB (Serverless) |
| 워밍업 로딩 시간 (Cold)<br>*(실행마다 변동 · 통계 제외)* | 2.145초 | 3.429초 | N/A |
| **모델 식별값 (Digest)** | `845dbda0ea48` | `46e0c10c039e` | N/A |
| **양자화 레벨** | `Q4_K_M` | `Q4_K_M` | FP16/BF16 |
| **실행 토큰 비용** | **$0.00 (온프레미스)** | **$0.00 (온프레미스)** | In: 1,277 / Out: 1,167 tokens |

> **지연 시간의 역설** — 토큰 생성 속도는 Llama가 15% 빠릅니다. 그런데 최종 응답 시간은 Qwen이 23% 짧습니다.
> Llama가 평균 117.6토큰을 쓰는 동안 Qwen은 76.4토큰으로 끝내기 때문입니다. 초당 처리량이 높아도 더 많이 쓰면 총 시간은 길어집니다.

> **포맷 준수율 산출 기준** — `src/triage_eval/common/score_format.py`가 원본 응답 45건을 6개 규칙(R1~R6)으로 자동 채점한 값입니다.<br>
> **엄격** 기준은 필드 사이 빈 줄까지 금지, **파서 호환** 기준은 빈 줄을 허용합니다.<br>
> Llama의 실패 사유는 전량 '필드 사이 빈 줄'이며, **서두 사족은 45건 전수에서 0건**이었습니다.<br>
> 규칙 정의와 회차별 판정은 [`report/format_compliance.md`](report/format_compliance.md) 참조.
>
> **성능 수치 산출 기준** — 지연·속도·토큰·VRAM은 `src/triage_eval/bench_v1/summarize_eval.py`가 원본 로그에서 재집계한 값입니다.
> 워밍업은 제외했고, 평균 속도는 회차별 `tokens_per_sec`의 단순 평균입니다. 집계 결과는 `data/results/benchmark_summary.json`에 저장됩니다.
>
> **워밍업 로딩 시간은 비교 지표가 아닙니다.** 디스크 캐시 상태에 따라 실행마다 달라지므로(재실행 시 4.065초 / 4.672초 관측) 값만 참고로 싣고 본 통계와 우열 판정에서 제외했습니다.

### 3) 5개 영역 QA 루브릭 정량 채점표 (100점 만점)

```text
[ 종합 품질 점수 ]
1. gpt-5.6-luna (Cloud) : ■■■■■■■■■■ 99점 (이상적 참조 기준선)
2. Qwen2.5-7B   (Local) : ■■■■■■■■□□ 81점 (최종 채택: 규격 준수 & 무결성)
3. Llama-3.1-8B (Local) : ■■■■■■■□□□ 77점 (탈락: Q08 환각 발생)
```

| 평가 영역 | 배점 | Qwen2.5-7B | Llama-3.1-8B | gpt-5.6-luna | 채점 및 핵심 분석 요약 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **정확성** | 25 | **21** | 19 | **24** | 결함 심각도 및 모듈 판정 타당성 (Llama: 가짜 결함 판정 -6) |
| **지시·형식 준수** | 25 | **24** | 21 | **25** | 5개 필드 Contract 준수 (Qwen: 사족 0건, Llama: 개행 과다 -4) |
| **핵심 정보 누락** | 20 | 15 | **19** | **20** | OS/기기/중복 단서 보존율 (Llama: Q01/Q10 단서 완벽 추출) |
| **정보 부족 대응** | 15 | 8 | 3 | **15** | 단문 인입 시 Fallback 정책 (Llama: 치명적 환각으로 -12) |
| **한국어 표현** | 15 | 13 | **15** | **15** | Jira 버그 등록에 적합한 실무 문체 (Qwen: 일부 비문 발생 -2) |
| **합계** | **100** | **81** | **77** | **99** | **로컬 1위: Qwen2.5-7B** |

> 루브릭 채점은 평가자 1인이 수행했으므로 주관이 포함됩니다.
> 주관이 개입하지 않는 지표는 모두 스크립트로 기계 채점했습니다.

### 4) 결정적 장면 — Q08 단문 리포트

점수 4점 차이가 모델을 가른 것이 아닙니다. 아래 한 케이스가 갈랐습니다.

**🚨 Llama-3.1-8B의 환각 (Hallucination)**

* **입력 (Q08)**: `"크래시남"` — 단 1단어
* **Run 1 응답**:
  > `[요약]: 게임 내 전투 모드에서 플레이어 캐릭터가 무한히 이동하는 결함 현상 발생`
* **Run 2 응답**:
  > `[누락 정보]: 추가 확인이 필요한 기기/OS/재현스텝: Windows 10, Intel Core i5, NVIDIA GeForce GTX 1660 Ti...`
* **QA 관점 리스크**: 입력에 전투 모드도, 이동도, 하드웨어 정보도 없습니다. 이 티켓이 Jira에 등록되면 **개발자가 존재하지 않는 버그를 GTX 1660 Ti로 재현하려 시간을 씁니다.**

**🛡️ Qwen2.5-7B의 파싱 계약(Contract) 안전성**

* 같은 입력에서 허위 정보를 만들지 않고 `누락 정보: 없음`으로 응답 — 소극적이지만 날조는 없음
* 20회 전 구간에서 시스템 지시문 외 사족(문두 인사, 서두 설명)을 차단
* Regex·문자열 파서 연동 시 줄바꿈/인덱스 밀림 예외(Index Error) 발생률 0%

> Qwen의 소극성은 4일차 Few-Shot 재실험에서 교정 가능함을 검증했습니다 (근거: `data/results/fewshot_verify.json`).

---

## 4. 실행 및 재현

### 1) 선행 환경 준비

* **Python**: 3.12 이상
* **패키지 관리자**: `uv` ([설치 문서](https://docs.astral.sh/uv/))
* **추론 런타임**: [Ollama](https://ollama.ai/) 설치 및 모델 다운로드

```powershell
ollama pull qwen2.5:7b
ollama pull llama3.1:8b
```

### 2) 클론 및 가상환경 동기화

```powershell
git clone https://github.com/kokoball-eval/game-bug-triage-llm-eval.git
cd game-bug-triage-llm-eval
uv sync
```

> `uv sync`는 의존성과 함께 이 저장소의 패키지(`src/triage_eval`)를 편집 가능 모드로 설치합니다. 이후 실행 명령은 `uv run <명령>` 형태입니다(`bench-run`, `triage-run` 등, 목록은 `pyproject.toml`의 `[project.scripts]`). 같은 동작을 `uv run python -m triage_eval.pipeline.run`처럼 모듈 경로로도 실행할 수 있습니다.

### 3) 실험 실행

```powershell
# 로컬 40회 본 실험 (워밍업 2회 자동 분리 · 10문항 × 2모델 × 2회)
uv run bench-run
# (v1.2) seed 고정 모드 — 1회차 seed=1, 2회차 seed=2. 측정 환경 경고가 있으면 멈춤
uv run bench-run --seed 1 --strict-env
# 결과를 문서 수치의 새 기준으로 삼을 때만
uv run bench-run --update-latest

# Cloud 대조군 (선택) — 실행 후 프롬프트에 OpenAI API Key 입력 (화면 미노출)
uv run python scripts/legacy/02_luna_chat.py

# 4일차 Few-Shot 단문 결함 교정 재실험
uv run python scripts/legacy/test_fewshot.py
```

> ℹ️ `src/triage_eval/bench_v1/run_eval.py` 는 실행 결과를 `data/results/history/local_eval_results_<실행시각>.json` 에만 저장합니다 (v1.1.1부터).
> `data/results/local_eval_results.json` 은 README·보고서 수치의 출처이므로, `--update-latest` 를 준 경우에만 교체됩니다.

### 4) 재현 검증 (Reproducibility Check)

본 실험 로그를 수정하지 않고 산출물만 다시 만들어 문서 수치를 검증하는 스크립트입니다.
모두 읽기 전용이거나 결과 파일만 덮어쓰므로 40회 본 실험 결과에는 영향을 주지 않습니다.

```powershell
# 성능 지표 재집계 (문서에 기재된 지연·속도·토큰 수치를 원본 로그에서 다시 계산)
uv run bench-summarize

# 포맷 계약 준수율 재채점 (원본 응답 45건을 R1~R6 규칙으로 다시 채점)
uv run bench-score-format

# 실행 환경 및 자원 점유 재측정 (CLI/Python 경로 검증 포함)
uv run bench-capture-env

# (v1.2) 환각 탐지 — 입력에 근거 없는 기기·OS·조작·시간 조건을 응답에서 찾음
uv run bench-hallucination
```

| 스크립트 | 입력 | 산출물 | 재현 확인 방법 |
| :--- | :--- | :--- | :--- |
| `src/triage_eval/bench_v1/summarize_eval.py` | `data/results/local_eval_results.json`, `cloud_eval_results.json` | `data/results/benchmark_summary.json`, 표준 출력 | 출력 표의 값이 3절 벤치마크 표 및 보고서 수치와 일치하는지 대조 |
| `src/triage_eval/common/score_format.py` | `data/results/local_eval_results.json`, `cloud_eval_results.json` | `data/results/format_compliance.json`, `report/format_compliance.md` | 회차별 판정과 집계율이 보고서 수치와 일치하는지 대조 |
| `src/triage_eval/bench_v1/capture_env.py` | 실행 중인 Ollama 런타임 | `data/results/environment.json`, `report/environment.md` | 산출 파일의 `captured_at` 으로 재실행 시점 확인 |
| `scripts/legacy/test_fewshot.py` | 고정 프롬프트 (Q08 단문) | `data/results/fewshot_verify.json` | `verdict.corrected` 값으로 교정 성공 여부 확인 |
| `src/triage_eval/bench_v1/compare_runs.py` | 기준선·후보 실행 로그, `gate_criteria.toml` | `data/results/gate_result.json`, `report/regression_gate.md` | 종료 코드(0/1/2)와 기준별 판정 확인 |
| `src/triage_eval/common/detect_hallucination.py` | 실행 로그, `data/questions.json` | `data/results/hallucination_report.json`, 표준 출력 | v1.0 로그에서 Llama Q08 2건만 탐지되고 Qwen·Cloud는 0건인지 확인 |

### 5) 회귀 게이트 — 두 실행 비교 (v1.1)

프롬프트·모델·Ollama 버전을 바꾼 뒤 **"이전보다 나빠졌는가"를 종료 코드 하나로 판정**합니다.
기본 기준선은 v1.2에서 찍은 **seed 고정 실행**(`data/results/baseline/v1.2_seed1_local_eval_results.json`)입니다. seed와 실행 조건이 기록돼 있어야 판정 변화까지 합격 기준으로 쓸 수 있기 때문입니다. README 수치의 출처인 v1.0 로그도 같은 폴더에 보존돼 있어 `--baseline`으로 지정할 수 있습니다.

```powershell
# 1) 새 실행 → 2) 고정 기준선(v1.2 seed=1)과 비교 (후보 기본값: history/ 의 가장 최근 실행)
uv run bench-run --seed 1 --strict-env
uv run bench-gate

# 파일 직접 지정 / 대조군 모델까지 판정
uv run bench-gate --baseline <기준선.json> --candidate <후보.json>
uv run bench-gate --model llama3.1:8b
```

| 종료 코드 | 의미 |
| :---: | :--- |
| `0` PASS | `gate_criteria.toml`의 모든 기준 통과 |
| `1` FAIL | 기준 1개 이상 미달 |
| `2` ERROR | 판정 불가 — 문항 구성 불일치, 실행 조건(옵션·프롬프트·문항·모델 digest) 변경, 기준 파일 오타 등. 의도한 조건 변경이면 `--allow-config-change` |

* **합격 기준**은 루트의 `gate_criteria.toml`에 있습니다. 절대 기준(바닥선)과 회귀 기준(기준선 대비 허용 악화폭) 두 종류이며, 기준마다 근거를 주석으로 달았습니다.
* 채점 규칙은 `score_format.py`, 지표 정의는 `summarize_eval.py`를 그대로 재사용하므로 README 표와 같은 숫자가 나옵니다.
* (v1.2) **날조 응답 0건**이 절대 기준에 추가됐습니다. 형식은 정상인데 입력에 없는 사실을 지어낸 응답을 막습니다.
* (v1.2) 심각도·모듈·재현 여부 **판정 변화**는 두 실행이 **같은 seed**로 돌았을 때만 합격 기준(`verdict_change_max`)으로 판정합니다. seed가 없거나 다르면 같은 조건에서도 흔들리므로 `⏭️ SKIP`(판정 생략)으로 표시하고 목록만 보여 줍니다. SKIP은 통과가 아니라 "이번 비교로는 판정할 수 없음"입니다.
* 결과: `data/results/gate_result.json`(기계 판독용), `report/regression_gate.md`(판정 근거)

### 6) 평가 도구 테스트 (v1.1.1)

채점·집계·게이트 로직이 **같은 입력에 같은 판정을 내는지** pytest로 검증합니다. 모델을 호출하지 않고 저장소의 실제 로그만 읽으므로 Ollama 없이 몇 초 안에 끝나며, `main` 브랜치에 push할 때마다 GitHub Actions가 자동 실행합니다.

```powershell
uv run pytest        # 전체
uv run pytest -v     # 테스트별 결과 표시
```

| 테스트 파일 | 검증하는 것 |
| :--- | :--- |
| `tests/test_score_format.py` | R1~R6 규칙이 각자 정확히 자기 위반만 잡는지, v1.0 로그 채점 결과가 README 준수율과 같은지 |
| `tests/test_summarize_eval.py` | half-up 반올림, 워밍업 제외, 결측 속도 처리, v1.0 로그 집계가 README 성능 표와 같은지 |
| `tests/test_compare_runs.py` | 게이트 판정(통과·실패·경계값), 비교 불가 조건, 기준 파일 오타 거부, 종료 코드 0/1/2, (v1.2) 날조 기준·seed별 판정 변화 기준·환경 경고 |
| `tests/test_detect_hallucination.py` | (v1.2) 범주별 탐지, 근거 있는 사실·요청 문맥·선택지 필드 오탐 방지, 실제 로그의 Llama Q08 날조 4건 전수 탐지와 Qwen·Cloud 오탐 0건 |
| `tests/test_preflight.py` | (v1.2) 측정 환경 경고 판정 (다른 프로그램의 GPU 사용, 배터리 구동, 측정 불가와 문제 있음의 구분) |
| `tests/test_run_eval.py` | (v1.2) seed 고정 모드의 회차별 seed, 기본 옵션 보존 |

* README 수치를 재현하는 테스트가 있어서, 채점·집계 코드를 고쳤을 때 **문서 수치가 더는 재현되지 않으면 테스트가 실패**합니다.
* 테스트를 추가하면서 경계값 버그 1건을 발견해 수정했습니다. 정확히 허용폭(+20%)만큼 느려진 경우 부동소수점 오차로 FAIL이 나던 문제입니다(`test_exactly_at_tolerance_passes`).
* (v1.2) 환각 탐지기도 테스트 단계에서 오탐 결함 2건이 걸러졌습니다([ISSUE-006](docs/issue_log.md#issue-006)).

### 7) 측정 환경 체크리스트와 seed 재현성 확인 (v1.2)

성능 지표는 모델이 같아도 측정 환경에 따라 크게 흔들립니다. 9/30 재실행에서 모델 파일은 그대로인데 Llama의 평균 지연이 +45.6% 늘었습니다([OBS-001](docs/issue_log.md#obs-001)). 벤치마크를 돌리기 전에 아래를 확인합니다.

| 확인 항목 | 이유 | 자동 점검 |
| :--- | :--- | :---: |
| 게임·영상·브라우저 등 GPU를 쓰는 프로그램 종료 | 같은 GPU를 나눠 쓰면 지연·속도가 흔들림 | ✅ Ollama 외 VRAM 1,024 MiB 이상이면 경고 |
| 노트북 전원 어댑터 연결 | 배터리 구동 시 GPU 클럭이 낮아질 수 있음 | ✅ Windows에서 경고 |
| 같은 seed로 실행 (`--seed 1`) | seed가 같아야 판정 변화를 합격 기준으로 쓸 수 있음 | — |

`run_eval.py`는 모델을 호출하기 전에 이 점검 결과를 화면에 출력하고 로그(`metadata.run_config.environment`)에 남깁니다. `--strict-env`를 주면 경고가 있을 때 실행하지 않습니다(종료 코드 2). `compare_runs.py`는 두 실행의 환경 경고와 전원 상태 차이를 함께 보여 줍니다.

**seed 재현성 확인 방법** — 같은 seed로 두 번 돌린 결과를 비교하면, 판정 변화가 0건이어야 합니다.

```powershell
uv run bench-run --seed 1 --strict-env      # 1차
uv run bench-run --seed 1 --strict-env      # 2차
uv run bench-gate --baseline data/results/history/<1차 파일>.json
```

**실측 결과 (2026-10-01, RTX 5060 Laptop · 전원 연결 · Ollama 외 VRAM 362~485 MiB)**

| 항목 | 결과 |
| :--- | :--- |
| 같은 seed 재실행 시 응답 원문 일치 | **40/40건** (생성 토큰 수도 40/40 일치) |
| 같은 seed 재실행 시 판정 변화 | **0건** → `verdict_change_max = 0` 유지 |
| 한 실행 안에서 1·2회차(seed 1 vs 2) 응답이 다른 문항 | 20문항 중 17개 → 회차 간 변동 관찰이라는 2회 반복 설계도 그대로 유지 |
| 깨끗한 환경에서 Llama 평균 속도 | 64.3 t/s (v1.0 66.56 / 9/30 재실행 44.9) → 9/30의 급락은 측정 환경 탓이었다는 해석을 뒷받침 ([OBS-001](docs/issue_log.md#obs-001)) |

첫 번째 실행은 기본 기준선(`baseline/v1.2_seed1_local_eval_results.json`)으로 고정했고, 두 실행 모두 `data/results/history/`에 보존했습니다.

> (v1.3) 같은 seed라도 **직전에 다른 프롬프트를 처리한 Ollama 프로세스**에서는 응답이 재현되지 않았습니다([OBS-002](docs/issue_log.md#obs-002)). 프롬프트를 바꿔 가며 측정할 때는 실행 전에 `ollama stop <모델>`로 모델을 내립니다.

### 8) v1.3 평가셋 실행·채점·회귀 게이트

```powershell
ollama stop qwen2.5:7b                                                       # 재현성 조건 (OBS-002)
uv run triage-run --seed 1 --strict-env --model qwen2.5:7b   # 개발용 32건 × 2회
uv run triage-score                                          # 정답 대조 채점
uv run triage-gate; echo "종료 코드: $LASTEXITCODE"           # 고정 기준선 대비 판정 (0 PASS · 1 FAIL · 2 판정 불가)
```

* 평가용(test) 문항은 `--final`을 줘야만 실행됩니다. 게이트는 개발용 실행만 판정합니다. v1.3 최종 측정은 `uv run triage-run --seed 1 --strict-env --split test --final`로 1회 실행했습니다(→ [`report/eval_v13_final.md`](report/eval_v13_final.md)).
* `--no-retry`, `--no-discard-check`, `--no-guardrail`로 형식 재요청·폐기 확인·후처리 안전장치를 끄면 모델 단독 성능을 잴 수 있습니다. 켜 둔 상태에서도 실행 기록에 모델 원본 응답(`raw_response_text`)이 함께 남습니다.
* 결과: `data/results/v13/gate_result_v13.json`(기계 판독용), `report/regression_gate_v13.md`(판정 근거)

---

## 5. 저장소 구조와 상세 보고서

### 1) 상세 기술 보고서

| 문서 | 담고 있는 것 |
| :--- | :--- |
| [`report/final_selection.md`](report/final_selection.md) | **최종 선정 보고서.** 4대 의사결정 축, 종합 스코어카드, 3단계 프로덕션 아키텍처, 프로젝트 한계 |
| [`report/model_comparison.md`](report/model_comparison.md) | **1~3일차 비교 분석서.** 실험 조건·프롬프트 전문, 평가 문항 10건, **벤치마크 코드 구성과 설계 의도**, 항목별 판정, Cloud 대조 심층 분석 |
| [`report/format_compliance.md`](report/format_compliance.md) | **포맷 준수율 채점 근거.** R1~R6 규칙 정의와 응답 45건의 회차별 판정 |
| [`report/environment.md`](report/environment.md) | **실행 환경 실측.** 시스템 RAM/VRAM 구분, 실측 context length, CLI/Python 경로 검증 |
| [`report/eval_v13_baseline.md`](report/eval_v13_baseline.md) | **(v1.3) 기준선 측정 보고서.** 개발용 세트 측정 조건, 결과, 오판 원인 분석 |
| [`report/eval_v13.md`](report/eval_v13.md) | **(v1.3) 정답 대조 채점 요약.** 모델·세트별 칸별 정답률, 위험 건, 날조 (`pipeline/score.py` 생성, 가장 최근 실행 기준) |
| [`report/eval_v13_final.md`](report/eval_v13_final.md) | **(v1.3) 최종 측정 보고서.** 평가용 세트 결과, 개발용 대비 비교, 모델 원본과 최종 출력 비교, 오답 원인 분석 |
| [`report/regression_gate.md`](report/regression_gate.md) | **회귀 게이트 판정 근거.** 기준선 대비 최신 실행의 지표·기준별 판정·판정 변화 (`compare_runs.py` 생성) |
| [`report/regression_gate_v13.md`](report/regression_gate_v13.md) | **(v1.3) 회귀 게이트 판정 근거.** 기준선 대비 후보 실행의 기준별 판정과 문항 단위 변화 (`gate_v13.py` 생성) |
| [`CHANGELOG.md`](CHANGELOG.md) | **버전별 변경 이력.** v1.0부터 v1.3까지, 버전마다 답하려는 질문 |
| [`docs/issue_log.md`](docs/issue_log.md) | **이슈 기록.** 고도화 중 발견한 결함, v1.3 실사용 시나리오, 알려진 한계, 관찰 사항을 현상 → 원인 → 조치 → 재발 방지 형식으로 정리 |
| [`docs/dataset/triage_guideline.md`](docs/dataset/triage_guideline.md) | **(v1.3) 트리아지 판정 기준서.** 분류·우선순위·처리·발생 빈도 규칙과 조항별 근거(인터뷰 출처) |
| [`docs/dataset/review_log.md`](docs/dataset/review_log.md) | **(v1.3) 평가셋 검토 기록.** 배치·전체 검토의 쟁점, 검토자 판단, 그에 따른 라벨·기준서 변경 |

### 2) 디렉터리 구조

<details>
<summary>전체 트리 펼치기</summary>

```text
game-bug-triage-llm-eval/
├── .github/workflows/tests.yml   # (v1.1.1) push 시 pytest 자동 실행 (GitHub Actions)
├── .gitattributes                # 줄바꿈(EOL) 정규화 규칙
├── .python-version               # Python 3.12 고정
├── pyproject.toml                # uv 기반 의존성 명세 (ollama, openai / 개발용 pytest)
├── gate_criteria.toml            # (v1.1) 회귀 게이트 합격 기준
├── gate_criteria_v13.toml        # (v1.3) 평가셋 회귀 게이트 합격 기준 (응답 수 기준 허용폭)
├── uv.lock                       # 의존성 잠금 파일 (재현 가능한 환경 구성)
├── README.md                     # 프로젝트 종합 대시보드 (본 문서)
├── CHANGELOG.md                  # 버전별 변경 이력
├── docs/
│   ├── issue_log.md              # 결함·알려진 한계 기록 (현상 → 원인 → 조치 → 재발 방지)
│   └── dataset/                  # (v1.3) 평가셋 근거 문서
│       ├── triage_guideline.md   # 판정 기준서 (조항별 근거)
│       ├── seed_plan.md          # 분류 체계·제보 품질 분포·문항 설계안
│       ├── interview_round1~4.md # 설계 인터뷰 기록 (질문·답변 요지·결정 사항)
│       └── review_log.md         # 배치·전체 검토의 쟁점·판단·반영 기록
├── data/
│   ├── questions.json            # 고정 벤치마크 10건 (정상 6, 경계 2, 예외 2)
│   ├── eval_v13/
│   │   └── aether_raid_v13.json  # (v1.3) 현업 기반 평가셋 63건 (정답 라벨, dev/test 분할)
│   └── results/
│       ├── qwen2.5_7b_verify.json       # 1일차 단일 호출 검증 로그
│       ├── llama3.1_8b_verify.json      # 1일차 단일 호출 검증 로그
│       ├── local_eval_results.json      # 2일차 로컬 40회 본 실험 원본 로그
│       ├── cloud_eval_results.json      # 3일차 Cloud 5회 비교 실험 원본 로그
│       ├── format_compliance.json       # 포맷 준수율 자동 채점 결과 (45건 회차별 판정)
│       ├── benchmark_summary.json       # 성능 지표 재집계 결과 (summarize_eval.py 생성)
│       ├── environment.json             # 실행 환경/자원 점유 실측값 (capture_env.py 생성)
│       ├── fewshot_verify.json          # 4일차 Few-Shot 교정 검증 응답 및 판정 근거
│       ├── gate_result.json             # (v1.1) 회귀 게이트 판정 결과 (compare_runs.py 생성)
│       ├── hallucination_report.json    # (v1.2) 환각 탐지 결과 (detect_hallucination.py 생성)
│       ├── baseline/
│       │   ├── v1.0_local_eval_results.json # (v1.1) v1.0 기준선 — README 수치의 출처, 덮어쓰지 않음
│       │   └── v1.2_seed1_local_eval_results.json # (v1.2) 기본 기준선 — seed=1, 깨끗한 환경
│       ├── history/                     # 실행 기록 (run_eval.py 실행마다 생성, compare_runs.py 기본 후보)
│       └── v13/                         # (v1.3) 평가셋 실행 기록(history/), 고정 기준선(baseline/), 채점 결과(score_*.json), 게이트 판정(gate_result_v13.json)
├── report/
│   ├── model_comparison.md      # 로컬 2종 vs Cloud 상세 정량/정성 분석서
│   ├── final_selection.md       # Qwen2.5 최종 선정 사유 및 배포 가드레일
│   ├── format_compliance.md     # 포맷 준수율 채점 규칙 및 회차별 판정 근거
│   ├── environment.md           # 시스템 RAM/VRAM 구분, 실측 context length 기록
│   ├── regression_gate.md       # (v1.1) 회귀 게이트 판정 근거 (compare_runs.py 생성)
│   ├── eval_v13_baseline.md     # (v1.3) 기준선 측정 보고서 (원인 분석)
│   ├── eval_v13.md              # (v1.3) 정답 대조 채점 요약 (pipeline/score.py 생성)
│   ├── eval_v13_final.md        # (v1.3) 평가용 세트 최종 측정 보고서
│   └── regression_gate_v13.md   # (v1.3) 회귀 게이트 판정 근거 (gate_v13.py 생성)
├── scripts/legacy/               # 5일 실험 당시의 일회용 스크립트 (v1.3 구조 정리 때 src/ 에서 이동)
│   ├── 01_ollama_chat.py         # 단일 모델 적재/VRAM 측정 스모크 테스트
│   ├── 02_luna_chat.py           # OpenAI Responses API Cloud 비교 스크립트
│   └── test_fewshot.py           # 4일차 Qwen 단문 결함 교정 Few-Shot 검증 스크립트
├── src/triage_eval/              # (v1.3 구조 정리) 패키지 — 실행 명령은 pyproject.toml [project.scripts]
│   ├── common/                   # v1.0 벤치마크와 현역 파이프라인이 함께 쓰는 도구
│   │   ├── paths.py              # 저장소 루트 경로 (한 곳에서만 정의)
│   │   ├── ollama_runtime.py     # 모델 digest·VRAM·프롬프트 지문 수집
│   │   ├── score_format.py       # 응답 줄 파서 + v1.0 포맷 계약 채점 (R1~R6)   → bench-score-format
│   │   ├── detect_hallucination.py # (v1.2) 입력에 근거 없는 구체 사실 탐지      → bench-hallucination
│   │   └── preflight.py          # (v1.2) 실행 전 측정 환경 점검 (GPU 점유·전원)
│   ├── bench_v1/                 # v1.0 모델 선정 벤치마크 (동결 — README 3절 수치의 출처)
│   │   ├── run_eval.py           # 워밍업 분리 40회 로컬 벤치마크                 → bench-run
│   │   ├── summarize_eval.py     # 성능 지표(지연·속도·토큰) 재집계              → bench-summarize
│   │   ├── compare_runs.py       # (v1.1) 두 실행 비교 + 회귀 게이트             → bench-gate
│   │   └── capture_env.py        # 실행 환경/자원 점유 실측 캡처                 → bench-capture-env
│   └── pipeline/                 # 현역 트리아지 파이프라인 (버전은 파일 이름이 아니라 코드 안 상수로 관리)
│       ├── contract.py           # 출력 형식 v2 — 8칸 정의·파싱·형식 채점 (R1~R7)
│       ├── prompt.py             # 판정 기준서 요약 프롬프트(v2.3)와 재요청·폐기 확인 질문 조립
│       ├── run.py                # 평가셋 실행 — 형식 재요청, 폐기 확인, 후처리 안전장치  → triage-run
│       ├── guardrail.py          # 후처리 안전장치 g2 — [처리] 규칙 보정 (정답 라벨 미사용)
│       ├── score.py              # 정답 대조 채점 (칸별 정답률·위험 건·과잉 상신·날조)   → triage-score
│       └── gate.py               # 평가셋 회귀 게이트 판정                               → triage-gate
├── tools/
│   └── dataset_v13/              # (v1.3) 평가셋 생성·병합·검증 스크립트 (정답 라벨의 원본)
└── tests/                        # (v1.1.1) 평가 도구 단위 테스트 (pytest)
    ├── conftest.py               # 공통 준비물 (기준선 로그 로드, 임시 파일)
    ├── test_score_format.py      # 포맷 채점 규칙 R1~R6
    ├── test_summarize_eval.py    # 성능 지표 집계 정의
    ├── test_compare_runs.py      # 회귀 게이트 판정·종료 코드
    ├── test_detect_hallucination.py # (v1.2) 환각 탐지 범주·오탐 방지·실제 로그 골든 테스트
    ├── test_preflight.py         # (v1.2) 측정 환경 경고 판정
    ├── test_run_eval.py          # (v1.2) seed 고정 모드
    ├── test_dataset_v13.py       # (v1.3) 평가셋 = 생성 스크립트 결과, 라벨 규칙 일관성, 분할 균형
    ├── test_pipeline_contract.py # (v1.3) 출력 형식 v2 채점 규칙 (R1~R7)
    ├── test_pipeline_score.py    # (v1.3) 정답 대조 채점, 가짜 모델로 실행→채점 전 과정
    ├── test_pipeline_run.py      # (v1.3) 평가용 실행 차단, 문항 유출 없음, 형식 재요청·폐기 확인
    ├── test_pipeline_guardrail.py # (v1.3) 후처리 안전장치 규칙, 정답 라벨 미사용, 원본 보존
    └── test_pipeline_gate.py     # (v1.3) 게이트 판정·비교 조건·기준 파일 검증
```

</details>

---

## 6. 프로덕션 도입 로드맵과 한계

### 1) 3대 가드레일 (프로덕션 파이프라인)

7B 소형 모델의 한계를 모델로 풀지 않고, 앞뒤에 룰과 사람을 두어 막는 구조입니다.

1. **Few-Shot 역질문 가드레일** — 단문 입력에서 `누락 정보: 없음`으로 처리되는 소극성을 보완하기 위해 시스템 프롬프트에 역질문 예시 1건 주입. *4일차 재실험에서 교정 검증 완료.*
2. **Two-Stage 이슈 분할기** — Q06처럼 다중 결함이 혼재된 리포트는 LLM 앞단의 룰 기반 경량 분할기로 쪼갠 뒤 순차 입력.
3. **Human-in-the-Loop 큐** — 심각도 `Blocker`/`Critical` 판정 또는 재현 여부 `불명확` 건은 Jira 자동 등록을 보류하고 QA 엔지니어 검토 큐로 라우팅.

> 파이프라인 도식과 설계 근거는 [`report/final_selection.md`](report/final_selection.md) §5에 있습니다.

### 2) 이 실험의 한계

* **표본 크기** — 고정 질문 10건을 40회 반복한 소규모 평가셋입니다. 실제 서비스의 엣지 케이스를 모두 대변하지는 못합니다.
* **평가자 1인** — QA 루브릭 채점에 주관이 포함됩니다. 이를 보완하기 위해 주관이 개입하지 않는 지표는 전부 스크립트로 기계 채점했습니다.
* **생성 시드 미고정** — `seed`를 지정하지 않아 회차마다 출력이 달라질 수 있습니다. 재실행 시 동일한 응답이 나오는 것을 보장하지 않습니다. 상세 영향 범위는 [`report/final_selection.md`](report/final_selection.md) §6에 기록했습니다.

---

## 7. 고도화 로드맵

### 최종 목표 — 사람이 보지 않아도 1차 트리아지가 돌아가는 파이프라인

v1.0은 "지금 어떤 모델이 이 업무에 맞는가"를 **한 번** 측정한 결과입니다.
최종 목표는 여기서 더 나아가, **유저 리포트가 들어오면 사람이 보고 있지 않아도 트리아지되어 BTS(버그 트래커)에 자동 등록되는 파이프라인**입니다.

다만 목표는 "사람 검토가 전혀 필요 없다"가 아닙니다. 7B 로컬 모델이 모든 리포트를 맞힐 수는 없으므로, **확신할 수 있는 건은 자동 등록하고, 확신할 수 없는 건은 시스템이 스스로 골라 QA 검토 큐로 보내는 구조**를 만들고, 그 성능을 숫자로 증명합니다.

| 최종 지표 | 뜻 | 목표 |
| :--- | :--- | :---: |
| **자동 처리율** | 전체 리포트 중 사람 손을 거치지 않고 등록된 비율 | 측정 후 설정 |
| **자동 처리분 정확도** | 자동 등록된 건의 심각도·모듈 판정이 정답과 일치한 비율 | 측정 후 설정 |
| **날조 건수** | 입력에 없는 사실(기기·조작·시간 조건 등)을 만들어 낸 응답 | **0건** |
| **위험 건 누락** | Critical 이상이거나 판단보류여야 할 건이 검토 없이 자동 등록된 건수 | **0건** |

> 목표 수치는 v1.3의 평가셋(개발용/평가용 분리)이 갖춰진 뒤 기준선을 재고 정합니다. 측정하지 않은 수치는 문서에 쓰지 않습니다.

### 버전별 계획

| 버전 | 답하려는 질문 | 작업 |
| :--- | :--- | :--- |
| ✅&nbsp;v1.0 | 어떤 모델이 이 업무에 맞는가? | 로컬 LLM 2종 비교·선정 |
| ✅&nbsp;v1.1 | 무언가 바꿨을 때 나빠졌는가? | 두 실행 비교 회귀 게이트 (`compare_runs.py`, `gate_criteria.toml`) |
| ✅&nbsp;v1.1.1 | 평가 도구 자체는 믿을 수 있는가? | 채점·게이트 로직 단위 테스트(pytest) + GitHub Actions CI |
| ✅&nbsp;v1.2 | 가장 위험한 결함(날조)을 사람 없이 잡을 수 있는가? | 환각 자동 탐지 + seed 고정 모드 + 측정 환경 체크리스트 |
| ✅&nbsp;v1.3 | 평가셋이 실제 현업 인입을 대표하는가? | ✅ 현업 기반 평가셋 63건 (분류 체계 → 판정 기준서 → 시드 케이스·정답 라벨), 개발용/평가용 분리 · ✅ 출력 형식 v2와 기준선 측정 · ✅ v1.3 게이트·실사용 시나리오 · ✅ 저장소 구조 정리 · ✅ 평가용 세트 최종 측정 |
| ⏳&nbsp;v1.4 | 정답 라벨과 자동 채점을 믿을 수 있는가? | 채점자 간 라벨 일치율 + LLM-as-judge와 사람 채점의 일치율 |
| ⏳&nbsp;v1.5 | 무엇을 자동 처리하고 무엇을 사람에게 넘길지 시스템이 판단할 수 있는가? | 확신도 기반 라우팅 + 자동 처리율·정확도·위험 건 누락 측정 |
| ⏳&nbsp;v2.0 | 사람이 보지 않는 동안에도 BTS에 올바르게 인입되는가? | BTS 자동 인입 (Redmine) + 중복 티켓 감지(RAG) + 무인 운영 데모 |

> ✅ 완료 · 🔨 다음 작업 · ⏳ 예정

### 버전별 상세

* **v1.1.1** — 모델을 호출하지 않는 채점·게이트 로직은 저장된 로그만으로 테스트할 수 있어 CI에서 자동 실행합니다. 검증 도구가 틀리면 모든 판정이 틀리기 때문입니다. 함께 `run_eval.py`가 문서 기준 로그를 기본으로 덮어쓰지 않게 바꿨습니다(→ [4-6)](#6-평가-도구-테스트-v111)).
* **v1.2** — 9/30 첫 재실행에서 확인된 두 공백(형식은 정상인 날조가 게이트를 통과, 판정 저하가 참고용이라 PASS)을 메웠습니다. 입력에 근거 없는 구체 사실을 규칙으로 탐지해 `hallucination_max = 0`을 기준에 넣었고, 같은 seed로 돈 두 실행에서는 판정 변화(`verdict_change_max = 0`)도 합격 기준으로 씁니다. 같은 seed 재실행 시 응답 40/40건이 일치해 이 기준이 노이즈 없이 동작함을 확인했습니다(→ [4-7)](#7-측정-환경-체크리스트와-seed-재현성-확인-v12)). 탐지기는 기존 4건에 더해 새 실행에서 처음 나온 날조 형태("3회 연속 패턴", "10분 정도 플레이 후")까지 잡았습니다. (근거: [`docs/issue_log.md`](docs/issue_log.md) KL-001·OBS-001)
* **v1.3** — 평가셋은 "현업에서 실제로 들어오는 리포트"를 대표해야 합니다. 게임 개발 QA 8년 경험을 채팅 인터뷰(4회)로 옮겨 다음 순서로 만들었습니다. 근거 문서는 모두 [`docs/dataset/`](docs/dataset/)에 있습니다.
  1. ✅ **분류 체계** — 입력을 두 트랙으로 나눴습니다. **트랙 A**는 커뮤니티 원문(목적: 걸러내기), **트랙 B**는 QA가 양식대로 쓴 BTS 이슈(BTS 인입의 약 95%, 목적: 우선순위 제안과 작성 품질 점검)입니다. 제보 품질(명확·단문·감정적 불만·복합·중복·문의·무관)의 비율은 실무 비율에 맞췄습니다 ([`seed_plan.md`](docs/dataset/seed_plan.md))
  2. ✅ **판정 기준서** — 분류 6종, 우선순위 6단계, 처리 6종, 발생 빈도 5종과 조항마다 근거를 적었습니다 ([`triage_guideline.md`](docs/dataset/triage_guideline.md)). Critical은 자동화가 개발팀에 직접 보내지 않고 **리드 QA 사인**을 거칩니다(`긴급 사인 요청`). 부서마다 판정이 갈리는 경계 사례 6종(P-B1~B6)은 정답 범위와 "사람 검토 필요" 표시를 둡니다
  3. ✅ **시드 케이스와 정답 라벨** — 63건(대표 세트 40 + 집중 세트 23). 문항 원문은 인터뷰에서 정한 시나리오를 바탕으로 Claude가 작성했고, 운영 불만형 5건은 직접 작성했습니다. 모든 문항과 라벨은 배치 검토 5회와 전체 검토 5회로 확정했으며, 쟁점과 판단, 반영 내용을 [`review_log.md`](docs/dataset/review_log.md)에 기록했습니다
  4. ⏭️ **변형** — v1.3에서는 하지 않았습니다. 63건 모두 사람이 문항별로 검토한 원문이라, 검수되지 않은 변형으로 수를 늘리기보다 검토된 원문만 쓰는 쪽을 택했습니다
  5. ✅ **개발용/평가용 분리** — 세트마다 반씩(대표 20/20, 집중 12/11) 나누되, 위험 건 측정 문항(Critical, 사람 검토)을 먼저 번갈아 배정해 양쪽에 고르게 들어가게 했습니다. 난수를 쓰지 않아 다시 실행해도 같은 분할이 나옵니다
  6. ✅ **출력 형식 v2와 기준선 측정** — 새 판정 체계용 8칸 출력 형식(`src/triage_eval/pipeline/contract.py`), 판정 기준서 요약 프롬프트(`src/triage_eval/pipeline/prompt.py`), 정답 대조 채점기(`src/triage_eval/pipeline/score.py`)를 만들고 개발용 32건으로 기준선을 쟀습니다. v1.0 파일은 수정하지 않고 별도 파일로 두어 v1.0 수치의 재현성을 유지했습니다. 평가용 세트는 `--final` 없이 실행되지 않습니다
     - Qwen2.5-7B 기준선: 형식 STRICT 89.1%, 처리 정답률 40.6%, **X-1 누락(Critical 미상신) 13/22**, 날조·결함 폐기·경계 건 확정 0건
     - 주원인: Critical 인식 실패(악용·이중 결제·필터 우회 등 피해가 쌓이는 유형을 Major로 판정), 명백한 결함을 "버그 아님"으로 분류, `개발 배정` 미사용 (→ [`report/eval_v13_baseline.md`](report/eval_v13_baseline.md))
     - 대조군 Llama3.1-8B는 형식 붕괴(대괄호 누락 16/64)와 판정 불안정(seed가 다른 두 회차에서 19/32문항 변화)으로, 새 평가셋에서도 Qwen 선정 판단이 유지됩니다
  7. ✅ **v1.3 회귀 게이트와 실사용 시나리오** — 위 기준선으로 합격 기준을 정하고(`gate_criteria_v13.toml`, `src/triage_eval/pipeline/gate.py`), 프롬프트 개선 과정을 게이트로 판정했습니다. 게이트 FAIL 5회를 거쳐 PASS에 이른 과정과 원인 분석은 [ISSUE-007](docs/issue_log.md#issue-007)에 기록했습니다
     - 기준선 → 최종(seed 1): X-1 누락 13 → 2, 처리 정답 26 → 48/64, 6칸 모두 정답 6 → 18, 형식 STRICT 57 → 64, 허용 값 위반 7 → 0, 날조·결함 폐기·경계 건 확정·언어 위반 0건, 평균 지연 +4.6%. seed 11·21에서도 절대 기준 0건 유지
     - 확인한 것: 7B 모델은 프롬프트 문장 1~2줄만 바꿔도 응답 64개 중 29~49개가 바뀌고, 규칙을 문장으로 강제하면 분류를 바꿔 규칙을 피해 갑니다. 형식 오류는 판단 오류를 가리고, "다시 써 달라"는 재요청은 같은 오류를 되풀이합니다
     - 그래서 **모델은 판단하고, 절차와 형식은 코드가 강제하는 구조**로 정리했습니다: 프롬프트 v2.3 → 형식 위반 필드만 재요청(구조화 출력의 enum·pattern으로 생성 단계 제한) → 폐기 직전 확인 질문 → 후처리 안전장치(`src/triage_eval/pipeline/guardrail.py`, [처리]만 보정)
     - 선택지 표기를 고친 프롬프트 v2.4는 seed 3쌍 비교에서 우선순위·처리 정답 하락과 과잉 상신 증가가 일관되게 나타나 기각했습니다
  8. ✅ **저장소 구조 정리 (v1.3 태그 전)** — `src/`를 패키지 `src/triage_eval/` 아래 공용 도구(`common/`), 동결된 v1.0 벤치마크(`bench_v1/`), 현역 파이프라인(`pipeline/`)으로 나누고, 일회용 스크립트는 `scripts/legacy/`로 옮겼습니다. 현역 파이프라인 파일 이름에서 버전을 빼(`run_eval_v2.py` → `pipeline/run.py` 등) 이후 버전은 같은 파일을 고쳐 나가고, 이전 버전은 git 태그로 보존합니다. 실행 명령은 `uv run triage-run`처럼 짧아졌습니다. 정리 전후의 동작이 같은지는 저장된 실행 기록 22건 재채점, 게이트 판정, 기록된 모델 응답 재생, 실제 모델 재측정으로 확인했습니다. 기존 경로 → 새 경로 대응표는 [`CHANGELOG.md`](CHANGELOG.md)에 있습니다
  9. ✅ **평가용 세트 최종 측정** — 개발 과정에서 한 번도 실행하지 않은 평가용 31건으로 최종 구성을 한 번 측정했습니다. 결과를 보고 프롬프트·안전장치·채점기를 고치지 않는다는 규칙을 미리 정했습니다 (→ [`report/eval_v13_final.md`](report/eval_v13_final.md))
     - **코드로 강제한 형식·절차는 일반화됐습니다**: 허용 값 위반·출력 언어 위반·결함 폐기 0건, 형식 STRICT 100%가 평가용에서도 유지됐습니다
     - **모델의 판단은 개발용에 맞춰져 있었습니다**: 개발용 → 평가용으로 우선순위 정답률 62.5% → 43.5%, X-1 누락 2/22 → 6/18, X-3 누락 0/12 → 4/10, 처리 정답률 75.0% → 62.9%. 놓친 Critical 5문항은 모두 프롬프트에 해당 규칙 문장이 있었는데도 판정되지 않았습니다 ([KL-003](docs/issue_log.md#kl-003))
     - 날조 2건은 같은 수량을 다른 단위로 옮긴 표현("100번" → "100회")을 탐지기가 날조로 잡은 오탐으로 판단하고, 측정값은 그대로 기록했습니다 ([ISSUE-008](docs/issue_log.md#issue-008))
     - 대조군 Llama3.1-8B는 평가용에서도 형식 STRICT 50%, X-1 누락 18/18로 Qwen 선정 판단이 유지됩니다
     - 이 결과로 v1.4의 과제가 분명해졌습니다: 판단 기준을 프롬프트 문장이 아닌 방식으로 전달하는 방법을 여러 seed로 비교하고, v1.5에서는 확신할 수 없는 건을 사람 검토 큐로 보내 위험 건 누락 0건을 지킵니다

  정답 라벨의 원본은 생성 스크립트([`tools/dataset_v13/`](tools/dataset_v13/))이고 JSON은 그 결과물입니다. 테스트가 둘의 일치와 라벨 규칙 간 일관성을 CI에서 확인합니다.

  실사용 시나리오(프롬프트 수정 → 게이트 FAIL → 원인 분석 → 수정 → PASS)는 [ISSUE-007](docs/issue_log.md#issue-007)에 기록했습니다. 남은 한계는 [KL-002](docs/issue_log.md#kl-002)에 있습니다.
* **v1.4** — 같은 기준서로 다른 채점자가 독립적으로 라벨을 달아 일치율을 잽니다. 일치하지 않는 건은 기준서가 모호하다는 신호이므로 기준서를 고칩니다. 이어서 LLM-as-judge의 채점이 사람 채점과 얼마나 일치하는지 측정해, 품질 채점 자동화를 어디까지 믿을 수 있는지 정합니다. 게이트 판정도 seed 하나가 아니라 여러 seed의 결과로 내리는 방식을 검토합니다(v1.3에서 seed에 따라 판정이 갈린 사례: [KL-002](docs/issue_log.md#kl-002)).
* **v1.5** — 응답의 확신도, 환각 탐지 결과, 판단보류·Critical 여부를 근거로 **자동 등록 / 검토 큐**를 나눕니다. 자동 처리율을 높이는 것보다 **위험 건 누락 0건을 지키는 것**이 우선입니다. v1.0 보고서의 Human-in-the-Loop 큐 설계([`report/final_selection.md`](report/final_selection.md) §5)를 실제로 구현하고 측정하는 단계입니다.
* **v2.0** — 리포트가 쌓이면 자동으로 감지해 트리아지하고, BTS에 등록합니다. BTS는 사내 설치형인 **Redmine**(Docker 로컬 실행)을 써서 "외부 API 전송 불가" 전제를 지키고, 공개 데모용으로 녹화 영상을 함께 남깁니다. 과거 티켓을 검색해 중복 제보(예: Q10과 Q01)를 묶는 RAG를 붙이며, 검색이 끼면서 생기는 새 실패 유형(엉뚱한 티켓을 중복으로 판정)도 기존 게이트 체계로 측정합니다.

---

## 8. 라이선스 (License)

본 프로젝트의 소스 코드와 데이터셋은 [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)에 따라 자유롭게 수정, 배포 및 상업적 용도로 활용할 수 있습니다.

> 참고: 평가에 사용한 모델의 라이선스는 본 프로젝트 라이선스와 별개입니다. `qwen2.5:7b`는 Apache 2.0, `llama3.1:8b`는 Llama 3.1 Community License를 따르며, 상세 조건은 [`report/model_comparison.md`](report/model_comparison.md) 모델 제원표의 Model Card 링크를 참조하세요.
