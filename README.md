# 🎮 Aether Raid Game Bug Report Triage Assistant
> **온디바이스 로컬 LLM 기반 인게임 결함 리포트 1차 트리아지 및 벤치마크 평가 자동화 파이프라인**

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/badge/uv-Fast%20Packaging-DE5FE9?logo=astral)](https://github.com/astral-sh/uv)
[![Inference Engine: Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-000000?logo=ollama)](https://ollama.ai/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

---

## 1. 프로젝트 개요 (Executive Summary)

라이브 서비스 게임 환경에서 인입되는 버그 리포트는 하루 수백~수천 건에 달하지만, 대다수가 단문·모호한 표현이거나 복합 결함이 섞여 있어 담당 QA 엔지니어의 1차 분류(Triage) 병목을 유발합니다.

본 프로젝트는 가상 게임 **"Aether Raid"**의 버그 리포트 인입 파이프라인을 상정하여, 사내 폐쇄망 환경에서 안전하게 동작 가능한 경량 로컬 LLM 2종(`qwen2.5:7b`, `llama3.1:8b`)의 실무 트리아지 성능을 비교·검증했습니다. 워밍업 분리 및 40회 반복 실험(문항당 2회)과 상용 클라우드 모델(`gpt-5.6-luna`) 대조군 검증을 통해 **데이터 무결성(환각 방지), 포맷 계약 준수율, 온디바이스 리소스 마진**을 종합 분석했습니다.

* **수행 형태**: 1인 단독 프로젝트 (환경 구성, 벤치마크 자동화 스크립트 작성, 정량/정성 평가 전 과정 수행)
* **실행 환경**: Windows 11 (AMD64), NVIDIA GeForce RTX 5060 Laptop GPU (VRAM 8,151 MiB), 시스템 RAM 31.4 GB, Ollama 0.34.0, Python 3.12.13 (`uv`) — 실측 근거: [`report/environment.md`](report/environment.md)

### 📌 엔지니어링 의사결정 여정 (Decision Journey)
* **1일차 (스모크 테스트)**: Llama-3.1이 고유명사 보존과 스키마 준수에서 우세 확인 → *"서두 사족만 가드레일로 잡으면 Llama가 승자"*라는 가설 수립
* **2일차 (40회 본 실험)**: 프롬프트 가드레일 주입 후 엣지 케이스(Q08 단문) 검증 중 **Llama의 치명적 환각(없는 결함 및 PC 사양 날조)** 발견
* **3일차 (Cloud 대조 검증)**: 상용 모델(`gpt-5.6-luna`, 99점) 대조를 통해 7B 소형 로컬 모델의 물리적 한계 실측 및 3대 프로덕션 아키텍처 도출
* **4일차 (가드레일 재실험)**: Qwen2.5에 단문 대응 Few-Shot 1건 주입 후 재실험 진행 → **소극적 태도 100% 교정 실측 입증**
* **최종 의사결정**: "소극성은 룰과 퓨샷으로 잡을 수 있지만, 날조는 파이프라인을 무너뜨린다"는 QA 무결성 기준에 따라 **Qwen2.5-7B 최종 선정**

### 🏆 최종 선정 모델: Qwen2.5-7B-Instruct (`qwen2.5:7b`, Q4_K_M)
* **데이터 무결성 확보**: Llama-3.1이 노출한 극단적 환각(단문 리포트에서 없는 결함 및 기기 사양 날조) 없이 원문 정보 왜곡 원천 방지
* **엄격한 규격 준수**: 5개 필드 트리아지 계약(Contract) 준수율 100%로 후속 Jira API 파싱 에러 제로 달성
* **하드웨어 효율성**: VRAM 4,528 MiB 점유로 Llama 대비 **499 MiB 절약**(두 모델 모두 시스템 RAM 오프로드 없이 100% GPU 적재) 및 평균 응답 지연 1.39초(Llama 대비 23% 고속)

> 📑 **상세 기술 보고서 바로가기**  
> * [1차·2일차 벤치마크 상세 비교 분석서 (`report/model_comparison.md`)](report/model_comparison.md)  
> * [Qwen2.5 최종 선정 보고서 및 실무 배포 전략 (`report/final_selection.md`)](report/final_selection.md)  
> * [포맷 준수율 채점 규칙 및 회차별 판정 근거 (`report/format_compliance.md`)](report/format_compliance.md)  
> * [실행 환경 및 자원 점유 실측 (`report/environment.md`)](report/environment.md)

---

## 2. 벤치마크 핵심 결과 (Benchmark Dashboard)

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
| **평균 생성 토큰 속도** | 58.74 tokens/s | **66.52 tokens/s** | N/A (Serverless API) |
| **평균 생성 토큰 수** | **76.5 tokens (핵심 압축)** | 117.6 tokens (다변 서술) | 233.4 tokens (상세 가이드) |
| **VRAM 점유량** | **4,528.1 MiB (~4.42 GB)** | 5,027.5 MiB (~4.91 GB) | 0 MiB (Serverless) |
| **워밍업 로딩 시간 (Cold)** | **2.145초** | 3.429초 | N/A |
| **모델 식별값 (Digest)** | `845dbda0ea48` | `46e0c10c039e` | N/A |
| **양자화 레벨** | `Q4_K_M` | `Q4_K_M` | FP16/BF16 |
| **실행 토큰 비용** | **$0.00 (온프레미스)** | **$0.00 (온프레미스)** | In: 1,277 / Out: 1,167 tokens |

> **포맷 준수율 산출 기준**: `src/score_format.py`가 원본 응답 로그 45건을 6개 규칙(R1~R6)으로 자동 채점한 값입니다. **엄격** 기준은 필드 사이 빈 줄까지 금지, **파서 호환** 기준은 빈 줄을 허용합니다. Llama의 실패 사유는 전량 '필드 사이 빈 줄'이며, **서두 사족은 45건 전수에서 0건**이었습니다. 규칙 정의와 회차별 판정은 [`report/format_compliance.md`](report/format_compliance.md) 참조.

---

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

---

## 3. QA 실무 결함 분석 사례 (Case Studies)

#### 🚨 치명적 결함: Llama-3.1-8B의 단문 리포트 환각 (Hallucination)
* **테스트 케이스 (Q08)**: `"크래시남"` (단 1단어 인입)
* **Llama-3.1 Run 1 응답**:
  > `[요약]: 게임 내 전투 모드에서 플레이어 캐릭터가 무한히 이동하는 결함 현상 발생`
* **Llama-3.1 Run 2 응답**:
  > `[누락 정보]: 추가 확인이 필요한 기기/OS/재현스텝: Windows 10, Intel Core i5, NVIDIA GeForce GTX 1660 Ti...`
* **QA 관점 리스크**: 입력에 없는 결함 증상과 하드웨어 스펙을 확정적으로 지어내어 개발/QA 조직의 리소스를 낭비시키는 고위험 결함 노출.

#### 🛡️ 규격 준수: Qwen2.5-7B의 파싱 계약(Contract) 안전성
* **출력 형식 일관성**: 전체 20회 추론 전 구간에서 시스템 지시문 외 사족(문두 인사, 서두 설명 등)을 완벽히 차단.
* **시스템 연동 이점**: Regex 및 문자열 파서 연동 시 줄바꿈/인덱스 밀림 예외(Index Error) 발생률 0%.

## 4. 저장소 디렉터리 구조 (Architecture)

```text
game-bug-triage-llm-eval/
├── .gitattributes                # 줄바꿈(EOL) 정규화 규칙
├── .python-version               # Python 3.12 고정
├── pyproject.toml                # uv 기반 의존성 명세 (ollama, openai)
├── uv.lock                       # 의존성 잠금 파일 (재현 가능한 환경 구성)
├── README.md                     # 프로젝트 종합 대시보드 (본 문서)
│       └── history/  # 실행 시각별 이력 사본
├── data/
│   ├── questions.json            # 고정 벤치마크 10건 (정상 6, 경계 2, 예외 2)
│   └── results/
│       ├── qwen2.5_7b_verify.json       # 1일차 단일 호출 검증 로그
│       ├── llama3.1_8b_verify.json      # 1일차 단일 호출 검증 로그
│       ├── local_eval_results.json      # 2일차 로컬 40회 본 실험 원본 로그
│       ├── cloud_eval_results.json      # 3일차 Cloud 5회 비교 실험 원본 로그
│       ├── format_compliance.json       # 포맷 준수율 자동 채점 결과 (45건 회차별 판정)
│       ├── environment.json             # 실행 환경/자원 점유 실측값 (capture_env.py 생성)
│       ├── fewshot_verify.json          # 4일차 Few-Shot 교정 검증 응답 및 판정 근거
│       └── history/                     # 실행 시각별 이력 사본 (run_eval.py 재실행 시 생성)

├── report/
│   ├── model_comparison.md      # 로컬 2종 vs Cloud 상세 정량/정성 분석서
│   ├── final_selection.md       # Qwen2.5 최종 선정 사유 및 배포 가드레일
│   ├── format_compliance.md     # 포맷 준수율 채점 규칙 및 회차별 판정 근거
│   └── environment.md           # 시스템 RAM/VRAM 구분, 실측 context length 기록
├── src/
│   ├── 01_ollama_chat.py         # 단일 모델 적재/VRAM 측정 스모크 테스트
│   ├── 02_luna_chat.py           # OpenAI Responses API Cloud 비교 스크립트
│   ├── run_eval.py               # 워밍업 분리 및 40회 로컬 자동 벤치마크 스크립트
│   ├── test_fewshot.py           # 4일차 Qwen 단문 결함 교정 Few-Shot 검증 스크립트
│   ├── score_format.py           # 포맷 계약 준수율 자동 채점 (R1~R6 규칙)
│   └── capture_env.py            # 실행 환경/자원 점유 실측 캡처
    
```

## 5. 재현 및 실행 가이드 (Quickstart)

### 1) 필수 선행 환경 준비
* **Python**: 3.12 이상
* **패키지 관리자**: `uv` ([설치 문서](https://docs.astral.sh/uv/))
* **추론 런타임**: [Ollama](https://ollama.ai/) 설치 및 모델 다운로드
  ```powershell
  ollama pull qwen2.5:7b
  ollama pull llama3.1:8b
  ```

### 2) 프로젝트 클론 및 가상환경 동기화
```powershell
git clone https://github.com/rkdwlrlarud-create/game-bug-triage-llm-eval.git
cd game-bug-triage-llm-eval
uv sync
```

### 3) 로컬 40회 벤치마크 실행
```powershell
# 워밍업 2회 자동 분리 및 10개 질문 x 2개 모델 x 2회 반복 = 40회 실행
uv run python src/run_eval.py
```

### 4) Cloud API 대조군 실행 (선택 사항)
```powershell
# 실행 후 프롬프트에 OpenAI API Key 입력 (화면 미노출)
uv run python src/02_luna_chat.py
```

### 5) 4일차 Few-Shot 단문 결함 교정 재실험
```powershell
# Q08 단문 리포트 결함 교정 실측 검증 (소극적 태도 -> 역질문 정상화)
# 결과는 data/results/fewshot_verify.json 에 응답 원문과 판정 근거로 저장됨
uv run python src/test_fewshot.py
```

## 6. 재실행 검증 (Reproducibility Check)

본 실험 로그를 수정하지 않고 산출물을 다시 만들어 검증하는 스크립트입니다. 모두 읽기 전용이거나 결과 파일만 덮어쓰므로, 40회 본 실험 결과에는 영향을 주지 않습니다.

```powershell
# 포맷 계약 준수율 재채점 (원본 응답 45건을 R1~R6 규칙으로 다시 채점)
uv run python src/score_format.py

# 실행 환경 및 자원 점유 재측정 (CLI/Python 경로 검증 포함)
uv run python src/capture_env.py
```

| 스크립트 | 입력 | 산출물 | 재현 확인 방법 |
| :--- | :--- | :--- | :--- |
| `src/score_format.py` | `data/results/local_eval_results.json`, `cloud_eval_results.json` | `data/results/format_compliance.json`, `report/format_compliance.md` | 회차별 판정과 집계율이 보고서 수치와 일치하는지 대조 |
| `src/capture_env.py` | 실행 중인 Ollama 런타임 | `data/results/environment.json`, `report/environment.md` | 산출 파일의 `captured_at` 으로 재실행 시점 확인 |
| `src/test_fewshot.py` | 고정 프롬프트 (Q08 단문) | `data/results/fewshot_verify.json` | `verdict.corrected` 값으로 교정 성공 여부 확인 |

> ⚠️ `src/run_eval.py` 는 재실행 시 `local_eval_results.json` 을 최신 결과로 덮어씁니다.
> ⚠️ 다만 실행할 때마다 동일한 내용이 `data/results/history/local_eval_results_<실행시각>.json` 으로도 저장되므로, 이전 실행 기록은 그대로 보존됩니다. 따라서 별도 백업이 필요하지 않습니다.

## 7. 프로덕션 도입 로드맵 (Production Action Items)

* **Few-Shot 가드레일 주입**
  * Qwen2.5의 단문 입력 대응 취약점(`누락 정보: 없음` 출력)을 보완하기 위해 시스템 프롬프트에 역질문 템플릿 예시 1건 추가.

* **복합 이슈 2단계 파이프라인 (Two-Stage Pipeline)**
  * Q06과 같이 다중 결함이 혼재된 리포트는 경량 이슈 스플리터로 분할한 후 트리아지 모델로 전달하는 파이프라인 설계.
  
* **Human-in-the-Loop 큐 연동**
  * 심각도 `Blocker`/`Critical` 판정 및 재현 여부 `불명확` 건은 완전 자동 등록을 차단하고 QA 리드의 승인 큐로 라우팅.

---

## 8. 라이선스 (License)
본 프로젝트의 소스 코드와 데이터셋은 [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0)에 따라 자유롭게 수정, 배포 및 상업적 용도로 활용할 수 있습니다.

> 참고: 평가에 사용한 모델의 라이선스는 본 프로젝트 라이선스와 별개입니다. `qwen2.5:7b`는 Apache 2.0, `llama3.1:8b`는 Llama 3.1 Community License를 따르며, 상세 조건은 [`report/model_comparison.md`](report/model_comparison.md) 모델 제원표의 Model Card 링크를 참조하세요.