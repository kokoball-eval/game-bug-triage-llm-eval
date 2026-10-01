# 🎮 Game Bug Report Triage Assistant

> **로컬 LLM 기반 인게임 결함 리포트 1차 트리아지 및 벤치마크 평가 자동화 파이프라인**

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

> **포맷 준수율 산출 기준** — `src/score_format.py`가 원본 응답 45건을 6개 규칙(R1~R6)으로 자동 채점한 값입니다.<br>
> **엄격** 기준은 필드 사이 빈 줄까지 금지, **파서 호환** 기준은 빈 줄을 허용합니다.<br>
> Llama의 실패 사유는 전량 '필드 사이 빈 줄'이며, **서두 사족은 45건 전수에서 0건**이었습니다.<br>
> 규칙 정의와 회차별 판정은 [`report/format_compliance.md`](report/format_compliance.md) 참조.
>
> **성능 수치 산출 기준** — 지연·속도·토큰·VRAM은 `src/summarize_eval.py`가 원본 로그에서 재집계한 값입니다.
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

### 3) 실험 실행

```powershell
# 로컬 40회 본 실험 (워밍업 2회 자동 분리 · 10문항 × 2모델 × 2회)
uv run python src/run_eval.py
# 결과를 문서 수치의 새 기준으로 삼을 때만
uv run python src/run_eval.py --update-latest

# Cloud 대조군 (선택) — 실행 후 프롬프트에 OpenAI API Key 입력 (화면 미노출)
uv run python src/02_luna_chat.py

# 4일차 Few-Shot 단문 결함 교정 재실험
uv run python src/test_fewshot.py
```

> ℹ️ `src/run_eval.py` 는 실행 결과를 `data/results/history/local_eval_results_<실행시각>.json` 에만 저장합니다 (v1.1.1부터).
> `data/results/local_eval_results.json` 은 README·보고서 수치의 출처이므로, `--update-latest` 를 준 경우에만 교체됩니다.

### 4) 재현 검증 (Reproducibility Check)

본 실험 로그를 수정하지 않고 산출물만 다시 만들어 문서 수치를 검증하는 스크립트입니다.
모두 읽기 전용이거나 결과 파일만 덮어쓰므로 40회 본 실험 결과에는 영향을 주지 않습니다.

```powershell
# 성능 지표 재집계 (문서에 기재된 지연·속도·토큰 수치를 원본 로그에서 다시 계산)
uv run python src/summarize_eval.py

# 포맷 계약 준수율 재채점 (원본 응답 45건을 R1~R6 규칙으로 다시 채점)
uv run python src/score_format.py

# 실행 환경 및 자원 점유 재측정 (CLI/Python 경로 검증 포함)
uv run python src/capture_env.py
```

| 스크립트 | 입력 | 산출물 | 재현 확인 방법 |
| :--- | :--- | :--- | :--- |
| `src/summarize_eval.py` | `data/results/local_eval_results.json`, `cloud_eval_results.json` | `data/results/benchmark_summary.json`, 표준 출력 | 출력 표의 값이 3절 벤치마크 표 및 보고서 수치와 일치하는지 대조 |
| `src/score_format.py` | `data/results/local_eval_results.json`, `cloud_eval_results.json` | `data/results/format_compliance.json`, `report/format_compliance.md` | 회차별 판정과 집계율이 보고서 수치와 일치하는지 대조 |
| `src/capture_env.py` | 실행 중인 Ollama 런타임 | `data/results/environment.json`, `report/environment.md` | 산출 파일의 `captured_at` 으로 재실행 시점 확인 |
| `src/test_fewshot.py` | 고정 프롬프트 (Q08 단문) | `data/results/fewshot_verify.json` | `verdict.corrected` 값으로 교정 성공 여부 확인 |
| `src/compare_runs.py` | 기준선·후보 실행 로그, `gate_criteria.toml` | `data/results/gate_result.json`, `report/regression_gate.md` | 종료 코드(0/1/2)와 기준별 판정 확인 |

### 5) 회귀 게이트 — 두 실행 비교 (v1.1)

프롬프트·모델·Ollama 버전을 바꾼 뒤 **"이전보다 나빠졌는가"를 종료 코드 하나로 판정**합니다.
기준선은 README 수치의 출처인 v1.0 로그를 `data/results/baseline/`에 고정해 두었습니다.

```powershell
# 1) 새 실행 → 2) 고정 기준선(v1.0)과 비교 (후보 기본값: history/ 의 가장 최근 실행)
uv run python src/run_eval.py
uv run python src/compare_runs.py

# 파일 직접 지정 / 대조군 모델까지 판정
uv run python src/compare_runs.py --baseline <기준선.json> --candidate <후보.json>
uv run python src/compare_runs.py --model llama3.1:8b
```

| 종료 코드 | 의미 |
| :---: | :--- |
| `0` PASS | `gate_criteria.toml`의 모든 기준 통과 |
| `1` FAIL | 기준 1개 이상 미달 |
| `2` ERROR | 판정 불가 — 문항 구성 불일치, 실행 조건(옵션·프롬프트·문항·모델 digest) 변경, 기준 파일 오타 등. 의도한 조건 변경이면 `--allow-config-change` |

* **합격 기준**은 루트의 `gate_criteria.toml`에 있습니다. 절대 기준(바닥선)과 회귀 기준(기준선 대비 허용 악화폭) 두 종류이며, 기준마다 근거를 주석으로 달았습니다.
* 채점 규칙은 `score_format.py`, 지표 정의는 `summarize_eval.py`를 그대로 재사용하므로 README 표와 같은 숫자가 나옵니다.
* 심각도·모듈·재현 여부 **판정 변화는 참고용 목록**으로만 출력합니다. seed 미고정 상태에서는 같은 조건에서도 흔들리기 때문이며, v1.2 seed 고정 후 합격 기준으로 승격할 예정입니다.
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
| `tests/test_compare_runs.py` | 게이트 판정(통과·실패·경계값), 비교 불가 조건, 기준 파일 오타 거부, 종료 코드 0/1/2 |

* README 수치를 재현하는 테스트가 있어서, 채점·집계 코드를 고쳤을 때 **문서 수치가 더는 재현되지 않으면 테스트가 실패**합니다.
* 테스트를 추가하면서 경계값 버그 1건을 발견해 수정했습니다. 정확히 허용폭(+20%)만큼 느려진 경우 부동소수점 오차로 FAIL이 나던 문제입니다(`test_exactly_at_tolerance_passes`).

---

## 5. 저장소 구조와 상세 보고서

### 1) 상세 기술 보고서

| 문서 | 담고 있는 것 |
| :--- | :--- |
| [`report/final_selection.md`](report/final_selection.md) | **최종 선정 보고서.** 4대 의사결정 축, 종합 스코어카드, 3단계 프로덕션 아키텍처, 프로젝트 한계 |
| [`report/model_comparison.md`](report/model_comparison.md) | **1~3일차 비교 분석서.** 실험 조건·프롬프트 전문, 평가 문항 10건, **벤치마크 코드 구성과 설계 의도**, 항목별 판정, Cloud 대조 심층 분석 |
| [`report/format_compliance.md`](report/format_compliance.md) | **포맷 준수율 채점 근거.** R1~R6 규칙 정의와 응답 45건의 회차별 판정 |
| [`report/environment.md`](report/environment.md) | **실행 환경 실측.** 시스템 RAM/VRAM 구분, 실측 context length, CLI/Python 경로 검증 |
| [`report/regression_gate.md`](report/regression_gate.md) | **회귀 게이트 판정 근거.** 기준선 대비 최신 실행의 지표·기준별 판정·판정 변화 (`compare_runs.py` 생성) |
| [`CHANGELOG.md`](CHANGELOG.md) | **버전별 변경 이력.** v1.0 → v1.1 → v1.1.1, 버전마다 답하려는 질문 |
| [`docs/issue_log.md`](docs/issue_log.md) | **이슈 기록.** 고도화 중 발견한 결함 5건과 알려진 한계를 현상 → 원인 → 조치 → 재발 방지 형식으로 정리 |

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
├── uv.lock                       # 의존성 잠금 파일 (재현 가능한 환경 구성)
├── README.md                     # 프로젝트 종합 대시보드 (본 문서)
├── CHANGELOG.md                  # 버전별 변경 이력
├── docs/
│   └── issue_log.md              # 결함·알려진 한계 기록 (현상 → 원인 → 조치 → 재발 방지)
├── data/
│   ├── questions.json            # 고정 벤치마크 10건 (정상 6, 경계 2, 예외 2)
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
│       ├── baseline/
│       │   └── v1.0_local_eval_results.json # (v1.1) 고정 기준선 — 덮어쓰지 않음
│       └── history/                     # 실행 기록 (run_eval.py 실행마다 생성, compare_runs.py 기본 후보)
├── report/
│   ├── model_comparison.md      # 로컬 2종 vs Cloud 상세 정량/정성 분석서
│   ├── final_selection.md       # Qwen2.5 최종 선정 사유 및 배포 가드레일
│   ├── format_compliance.md     # 포맷 준수율 채점 규칙 및 회차별 판정 근거
│   ├── environment.md           # 시스템 RAM/VRAM 구분, 실측 context length 기록
│   └── regression_gate.md       # (v1.1) 회귀 게이트 판정 근거 (compare_runs.py 생성)
├── src/
│   ├── 01_ollama_chat.py         # 단일 모델 적재/VRAM 측정 스모크 테스트
│   ├── 02_luna_chat.py           # OpenAI Responses API Cloud 비교 스크립트
│   ├── run_eval.py               # 워밍업 분리 및 40회 로컬 자동 벤치마크 스크립트
│   ├── test_fewshot.py           # 4일차 Qwen 단문 결함 교정 Few-Shot 검증 스크립트
│   ├── score_format.py           # 포맷 계약 준수율 자동 채점 (R1~R6 규칙)
│   ├── summarize_eval.py         # 성능 지표(지연·속도·토큰) 재집계
│   ├── compare_runs.py           # (v1.1) 두 실행 비교 + 회귀 게이트 판정
│   └── capture_env.py            # 실행 환경/자원 점유 실측 캡처
└── tests/                        # (v1.1.1) 평가 도구 단위 테스트 (pytest)
    ├── conftest.py               # 공통 준비물 (기준선 로그 로드, 임시 파일)
    ├── test_score_format.py      # 포맷 채점 규칙 R1~R6
    ├── test_summarize_eval.py    # 성능 지표 집계 정의
    └── test_compare_runs.py      # 회귀 게이트 판정·종료 코드
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
| 🔨&nbsp;v1.2 | 가장 위험한 결함(날조)을 사람 없이 잡을 수 있는가? | 환각 자동 탐지 + seed 고정 모드 + 측정 환경 체크리스트 |
| ⏳&nbsp;v1.3 | 평가셋이 실제 현업 인입을 대표하는가? | 현업 기반 평가셋 구축 (분류 체계 → 판정 기준서 → 시드 케이스 → 변형), 개발용/평가용 분리 |
| ⏳&nbsp;v1.4 | 정답 라벨과 자동 채점을 믿을 수 있는가? | 채점자 간 라벨 일치율 + LLM-as-judge와 사람 채점의 일치율 |
| ⏳&nbsp;v1.5 | 무엇을 자동 처리하고 무엇을 사람에게 넘길지 시스템이 판단할 수 있는가? | 확신도 기반 라우팅 + 자동 처리율·정확도·위험 건 누락 측정 |
| ⏳&nbsp;v2.0 | 사람이 보지 않는 동안에도 BTS에 올바르게 인입되는가? | BTS 자동 인입 (Redmine) + 중복 티켓 감지(RAG) + 무인 운영 데모 |

> ✅ 완료 · 🔨 다음 작업 · ⏳ 예정

### 버전별 상세

* **v1.1.1** — 모델을 호출하지 않는 채점·게이트 로직은 저장된 로그만으로 테스트할 수 있어 CI에서 자동 실행합니다. 검증 도구가 틀리면 모든 판정이 틀리기 때문입니다. 함께 `run_eval.py`가 문서 기준 로그를 기본으로 덮어쓰지 않게 바꿨습니다(→ [4-6)](#6-평가-도구-테스트-v111)).
* **v1.2** — 첫 재실행(2026-09-30)에서 두 가지 공백이 확인됐습니다. Llama의 Q08 날조가 재현됐지만 형식은 정상이라 게이트의 어떤 기준에도 걸리지 않았고, Qwen의 Q07 재현 여부가 `불명확`→`발생(100%)`으로 나빠졌지만 판정 변화는 아직 합격 기준이 아닙니다. 환각 탐지를 기준에 추가하고, seed를 고정한 뒤 판정 변화를 합격 기준으로 승격합니다. 같은 재실행에서 측정 환경 차이로 성능 지표가 크게 흔들린 것도 확인돼, 벤치마크 실행 전 체크리스트를 함께 둡니다. (근거: [`docs/issue_log.md`](docs/issue_log.md) KL-001·OBS-001)
* **v1.3** — 평가셋은 "현업에서 실제로 들어오는 리포트"를 대표해야 합니다. 이를 위해 다음 순서로 만듭니다.
  1. **분류 체계** — 결함 유형(크래시·진행 불가·재화/결제·표시 오류·네트워크 등) × 제보 품질(재현 절차 명확·단문·감정적 불만·복합 이슈·중복·버그 아닌 문의·스팸)의 표와, 실제 인입에 가까운 비율을 게임 개발 QA 8년 경험으로 설계
  2. **판정 기준서** — "결제 후 재화 미지급은 재현 여부와 무관하게 Critical 이상"처럼 심각도·모듈 판정 규칙을 문서로 먼저 정의
  3. **시드 케이스와 정답 라벨** — 공개 커뮤니티 제보의 문체·누락 패턴을 참고해 가상 게임 "Aether Raid"용으로 새로 작성하고(원문 복사 없음), 기준서 조항을 근거로 정답을 라벨링
  4. **변형** — AI는 시드 케이스의 말투·오타·줄임말 변형에만 사용하고, 케이스 자체를 지어내지 않음. 모든 변형은 사람이 검수
  5. **개발용/평가용 분리** — 프롬프트 튜닝은 개발용으로만 하고, 평가용은 최종 수치 측정에만 사용

  평가셋이 갖춰지면 **실사용 시나리오 1건**을 기록합니다. 프롬프트를 개선하려고 수정 → 게이트가 특정 문항의 판정 저하로 FAIL → 원인 분석 → 수정 → PASS까지의 실제 과정을 이슈 기록에 남깁니다.
* **v1.4** — 같은 기준서로 다른 채점자가 독립적으로 라벨을 달아 일치율을 잽니다. 일치하지 않는 건은 기준서가 모호하다는 신호이므로 기준서를 고칩니다. 이어서 LLM-as-judge의 채점이 사람 채점과 얼마나 일치하는지 측정해, 품질 채점 자동화를 어디까지 믿을 수 있는지 정합니다.
* **v1.5** — 응답의 확신도, 환각 탐지 결과, 판단보류·Critical 여부를 근거로 **자동 등록 / 검토 큐**를 나눕니다. 자동 처리율을 높이는 것보다 **위험 건 누락 0건을 지키는 것**이 우선입니다. v1.0 보고서의 Human-in-the-Loop 큐 설계([`report/final_selection.md`](report/final_selection.md) §5)를 실제로 구현하고 측정하는 단계입니다.
* **v2.0** — 리포트가 쌓이면 자동으로 감지해 트리아지하고, BTS에 등록합니다. BTS는 사내 설치형인 **Redmine**(Docker 로컬 실행)을 써서 "외부 API 전송 불가" 전제를 지키고, 공개 데모용으로 녹화 영상을 함께 남깁니다. 과거 티켓을 검색해 중복 제보(예: Q10과 Q01)를 묶는 RAG를 붙이며, 검색이 끼면서 생기는 새 실패 유형(엉뚱한 티켓을 중복으로 판정)도 기존 게이트 체계로 측정합니다.

---

## 8. 라이선스 (License)

본 프로젝트의 소스 코드와 데이터셋은 [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)에 따라 자유롭게 수정, 배포 및 상업적 용도로 활용할 수 있습니다.

> 참고: 평가에 사용한 모델의 라이선스는 본 프로젝트 라이선스와 별개입니다. `qwen2.5:7b`는 Apache 2.0, `llama3.1:8b`는 Llama 3.1 Community License를 따르며, 상세 조건은 [`report/model_comparison.md`](report/model_comparison.md) 모델 제원표의 Model Card 링크를 참조하세요.
