# 변경 이력 (Changelog)

이 프로젝트의 버전별 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며, 각 버전이 **어떤 질문에 답하기 위해** 만들어졌는지를 함께 적습니다.
진행 중 발견한 결함과 조치 내역은 [`docs/issue_log.md`](docs/issue_log.md)에 따로 기록합니다.

---

## [Unreleased] — v1.4

### 추가 (1단계: 모델 재선정)
- `src/triage_eval/pipeline/screen.py` (`uv run triage-screen`) — 후보 모델 사전 점검. 개발용 3건으로 설치·생각 끄기·GPU 적재·구조화 출력·출력 형식(R2·R7)만 확인하고 정답률은 기록하지 않음. 평가용 문항은 쓰지 않음
  - GPU 적재 판정은 ps 보고 크기가 모델 파일보다 작으면 판정 불가(HOLD). ps 원본·모델 파일 크기·nvidia-smi VRAM·생성 속도를 함께 기록 ([ISSUE-009](docs/issue_log.md#issue-009), [OBS-003](docs/issue_log.md#obs-003))
- `src/triage_eval/pipeline/selection.py` (`uv run triage-select`), `model_selection_v14.toml` — 현재 모델 vs 후보 모델 교체 판정. seed 3개의 실행 기록에서 모델 외 조건(프롬프트·재요청·폐기 확인·안전장치·생각 끄기 포함)이 모두 같아야 판정. 절대·회귀 기준 값은 `gate_criteria_v13.toml`을 그대로 읽고, 지연은 증가율 대신 1건 평균 10초 이하를 절대 기준으로 씀
  - 교체 규칙(측정 전 확정): 모든 seed에서 기준 통과 + seed 합계로 X-1 누락 감소(같으면 우선순위 정답 증가). 개선이 없으면 현재 모델 유지
- 테스트 173 → 199개

### 변경
- `run.py` — 모든 모델 호출에 `think=False`, 실행 기록에 `run_config.think`. 모델마다 실행 전에 메모리에서 내림(OBS-002의 `ollama stop`을 코드로 옮김). 기본 대상 모델을 `qwen2.5:7b` 하나로 변경(Llama 3.1은 정기 측정에서 제외)
- 동작 동일성 확인: 변경 후 qwen2.5:7b 개발용 seed 1의 모델 원본·최종 응답 64/64가 v1.3 실행 기록과 같음

### 수정 (2단계: 날조 탐지기)
- `detect_hallucination.py` — 같은 수량을 다른 횟수 단위로 옮긴 응답("100번"→"100회", "한 번"→"1회")을 날조로 판정하던 오탐 수정. 숫자·고유어 수사 + 번·회·연·차례를 같은 횟수로 비교하고, "N번째"·"번호"는 제외 ([ISSUE-008](docs/issue_log.md#issue-008))
- 수정 전후 저장된 응답 2,545건 재판정: 바뀐 판정 8건(모두 이 오탐 사례), v1.0 결과 변화 없음. v1.4 모델 재선정 결정은 다시 판정해도 같음
- 테스트 199 → 211개

### 추가 (3단계: 새 최종 평가용 세트)
- `data/eval_v14/aether_raid_v14.json` — v1.3의 63건을 모두 개발용(dev)으로 돌리고(원래 분할은 `split_v13`), 새 최종 평가용 세트 25건(F01~F25, 분할 `final`)을 더한 88건. v1.3 평가용 31건은 v1.3 최종 측정에서 결과를 이미 확인해 평가용으로 다시 쓸 수 없기 때문
  - 시나리오는 검토자 제시, 원문과 라벨 초안은 Claude 작성, 검토 2회로 확정 ([검토 기록](docs/dataset/review_log.md), [25건 전문](docs/dataset/final_v14_review.md))
  - 방법 선택이 끝날 때까지 실행하지 않음. 기존 실행 스크립트의 분할 선택지에 `final`이 없어 실수로도 실행되지 않음
- `tools/dataset_v14/` — 생성(`build_v14.py`)·검토 문서 생성(`render_review.py`)·25건 라벨 원본(`final_v14_items.py`). v1.3 평가셋 파일과 생성 스크립트는 변경 없음
- 테스트 211 → 218개 (`tests/test_dataset_v14.py`: 생성 결과 일치, 63건 라벨 무변경, 기존 원문 재사용 없음, 검증 규칙 완화 범위)

### 변경 (3단계: 기준서·검증)
- 판정 기준서 v1.3 → v1.4 — F-2 예외에 단서 추가: 드문 조건에서만 생기고 우회 가능한 무료 보상 손실은 Major까지 낮출 수 있음(유료 재화는 Critical 유지). 기존 63건의 라벨 변화 없음
- v1.4 생성기의 트랙 A 개발 배정 검증을 "허용 분류에 개선 제안이 있으면 허용"으로 완화 (v1.3 도구는 그대로)

### 변경 (4단계: 실행·채점 도구가 v1.4 평가셋을 읽도록)
- `run.py` — `--dataset v13|v14` 추가(기본 v13). `--split final` 추가, final도 test와 같이 `--final`이 있어야 실행. 고른 평가셋에 없는 분할이라 문항이 0건이면 실행하지 않고 종료 코드 2. v1.4 실행 기록은 `data/results/v14/history/`에 따로 남김
- `score.py` — 정답 라벨을 실행 기록의 `dataset_version`으로 고름(v1.3 → v13, v1.4 → v14, 그 외는 채점 거부). `--dataset`은 `--log` 생략 시 최근 실행을 찾을 폴더만 정함. v1.4 보고서는 `report/eval_v14.md`
- 게이트(`gate.py`)·모델 선정(`selection.py`)·사전 점검(`screen.py`)은 변경 없음 (v1.3 폴더·평가셋만 봄)
- 동작 동일성 확인: 저장된 v1.3 실행 기록 27개를 변경 전후 코드로 다시 채점해 채점 결과 JSON 27개가 모두 같고, 보고서는 실행 기록 경로 표기 외에 같음
- 테스트 218 → 225개

### 모델 재선정 (2026-10-02~03, 개발용 32건 × 2회 × seed 3개)
- 후보 8개 → 조건(한국어·VRAM 8GB·상업 라이선스·구조화 출력)으로 6개 사전 점검 → gemma4:12b·granite4:tiny-h 비교 측정
- **결정: 현재 모델(qwen2.5:7b) 유지** — 두 후보 모두 seed 3개 전부에서 기준 미통과
- gemma4:12b: X-1 누락 8→3, 우선순위 정답 119→158(seed 합계)로 판단은 앞섰으나, X-3(B12)·과잉 상신·처리 문항 회귀가 모든 seed의 같은 문항에서 반복. 날조 판정 6건은 탐지기 오판([ISSUE-008](docs/issue_log.md#issue-008) 재현)이나 제외해도 결론 동일
- 한계: 프롬프트 v2.3이 현재 모델에 맞춰져 있음 ([KL-004](docs/issue_log.md#kl-004))
- 보고서: [`report/eval_v14_model_selection.md`](report/eval_v14_model_selection.md)

---

## [v1.3] — 2026-10-02

> **답하려는 질문:** 평가셋이 실제 현업 인입을 대표하는가?

### 추가 (1단계: 평가셋)
- `data/eval_v13/aether_raid_v13.json` — 현업 기반 평가셋 63건 (대표 세트 40: 트랙 A 커뮤니티 원문 20 + 트랙 B QA 작성 이슈 20 / 집중 세트 23: 운영 불만형·경계 사례·감정 속 진짜 결함·확인 필요·거짓 경보)
  - 정답 라벨 7종(분류·우선순위·모듈·재현 정보·발생 빈도·처리·사람 검토)과 위험 건 측정 표시(X-1~X-3), 반드시 요청할 정보·권장 조치
  - 개발용/평가용 분할 (대표 20/20, 집중 12/11 — 위험 건 측정 문항을 먼저 번갈아 배정)
- `docs/dataset/` — 판정 기준서, 문항 설계안, 설계 인터뷰 기록 4회, 검토 기록(배치 검토 5회 + 전체 검토 5회의 쟁점·판단·반영)
- `tools/dataset_v13/` — 배치별 생성 스크립트(정답 라벨의 원본), 병합·분할·검증(`merge_dataset.py`), 검토 문서 렌더러
- `tests/test_dataset_v13.py` — 저장소의 JSON이 생성 스크립트 결과와 같은지, 라벨 규칙 간 일관성 검사가 오류를 잡는지, 분할이 균형인지 (테스트 85 → 92)

### 추가 (2단계: 출력 형식 v2와 기준선)
- `src/contract_v2.py` — 8칸 출력 형식(요약·분류·모듈·우선순위·재현 정보·발생 빈도·처리·누락 정보) 정의와 형식 채점 R1~R6
- `src/prompt_v2.py` — 판정 기준서 요약 프롬프트와 입력 조립(입력 종류·업데이트 공지·기존 등록 이슈 포함)
- `src/run_eval_v2.py` — 평가셋 실행. 개발용이 기본이며 평가용은 `--final` 없이 실행되지 않음. `num_ctx` 8192 명시와 입력 토큰 수 기록
- `src/score_v2.py` — 정답 대조 채점(칸별 정답률 허용·최선, 6칸 정답, 위험 건 X-1~X-3, 과잉 상신, 날조, 요청·권장 반영은 참고 지표)
- 테스트 22개 추가 (92 → 114): 형식 채점, 정답 대조, 평가용 실행 차단, 프롬프트에 문항 유출 없음, 가짜 모델로 실행→채점 전 과정
- 기존 `src/` 파일은 수정하지 않음 (v1.0 로그 형식과 수치의 재현성 유지)

### 기준선 측정 (2026-10-02, 개발용 32건 × 2회)
- Qwen2.5-7B: STRICT 89.1%, 처리 정답률 40.6%, X-1 누락 13/22, X-2·X-3·날조 0건, 판정 변화 4/32문항
- Llama3.1-8B: STRICT 71.9%(대괄호 누락 16건), 처리 정답률 23.4%, X-1 누락 16/22, 판정 변화 19/32문항
- 원인 분석: [`report/eval_v13_baseline.md`](report/eval_v13_baseline.md)

### 판정 체계 변경 (v1.0 10문항·출력 형식은 그대로 보존)
- `[심각도]` → `[우선순위]` (Critical / Major / Minor / Trivial / 판단보류 / 해당 없음) — 실무는 심각도 대신 우선순위 4단계를 썼음
- `[재현 여부]` → `[재현 정보]`(충분 / 부족) + `[발생 빈도]`(항상 / 간헐적 / 1회 / 미기재 / 해당 없음) — 모델은 재현 성공 여부를 알 수 없으므로, 리포트에 적힌 빈도만 옮김
- `[분류]`, `[처리]` 신설 — 처리 6종 중 `긴급 사인 요청`은 Critical을 리드 QA 사인 후 개발에 전달한다는 뜻 (자동화가 Critical을 직접 보내지 않음)

### 추가 (3단계: 회귀 게이트와 실사용 시나리오)
- `gate_criteria_v13.toml`, `src/gate_v13.py` — v1.3 회귀 게이트. 기준선과 후보를 같은 채점기로 다시 채점해 판정 (종료 코드 0/1/2)
  - 절대 기준: 호출 성공 100%, 날조·X-2·X-3·출력 언어 위반(R7)·허용 값 위반(R6) 0건
  - 회귀 기준(응답 수): X-1 증가 0, 과잉 상신 증가 ≤ 2, 형식 하락 ≤ 2, 지연 증가 ≤ 20%, 칸별 정답 하락(처리·분류 0, 우선순위 1, 나머지 3), 문항 단위 회귀(처리·분류 ≤ 2)
  - 비교 조건(평가셋·옵션·문항·seed·모델 digest)이 다르거나 평가용 문항이 섞이면 판정 거부. 프롬프트·안전장치·재요청·폐기 확인 정책 변경은 판정 메모에 표시
- `src/guardrail_v2.py` — 후처리 안전장치 g2. 판단 필드를 읽을 수 없으면 확정 처리 차단(H-0), Critical은 긴급 사인 요청(H-1), 트랙 A 결함 개발 배정 → 재현 대기(H-2), QA 작성 결함 재현 대기 → 개발 배정(H-2b). [처리]만 보정하며 정답 라벨은 보지 않음
- `run_eval_v2.py` 형식 재요청 — 허용 값 위반(R6)·출력 언어 위반(R7) 필드만 1회 재요청. 선택지 필드는 JSON 스키마 enum, 자유 서술 필드는 허용 문자 pattern으로 생성 단계에서 제한
- `run_eval_v2.py` 폐기 확인 질문 — 최종 처리가 폐기(중복 의심 제외)이면 "이상 현상 제보 / 무관"을 1회 확인 (판정 기준서 H-9)
- 실행 기록에 모델 원본 응답(`raw_response_text`), 재요청·폐기 확인 내역(`attempts`), 안전장치 적용 내역(`guardrail`) 기록
- 테스트 59개 추가 (114 → 173)

### 변경
- 출력 형식 v2에 R7(출력 언어) 추가. 판정은 허용 목록 방식(한글·ASCII·일부 기호 외 문자는 위반)
- 프롬프트 v2.0 → v2.3 (v2.1 원인 분석 반영, v2.2 언어 규칙, v2.3 = v2.1 + 언어 규칙 1줄). v2.4(선택지 표기 변경)는 seed 3쌍 측정 결과로 기각

### 실사용 시나리오 (2026-10-02, 개발용 32건 × 2회, Qwen2.5-7B)
- 게이트 FAIL 5회 → PASS. 경과와 원인 분석: [ISSUE-007](docs/issue_log.md#issue-007)
- 기준선 → 최종(seed 1): X-1 13 → 2, 처리 정답 26 → 48, 6칸 모두 정답 6 → 18, 형식 STRICT 57 → 64, 허용 값 위반 7 → 0, 날조·X-2·X-3·언어 위반 0건, 평균 지연 +4.6%
- seed 11·21에서도 절대 기준 0건 유지. 남은 한계: [KL-002](docs/issue_log.md#kl-002), 재현성 조건: [OBS-002](docs/issue_log.md#obs-002)

### 변경 (4단계: 저장소 구조 정리)
- `src/`를 패키지 `src/triage_eval/`로 바꾸고 공용 도구(`common/`), 동결된 v1.0 벤치마크(`bench_v1/`), 현역 파이프라인(`pipeline/`)으로 나눔. 일회용 스크립트는 `scripts/legacy/`로 이동
- 현역 파이프라인 파일 이름에서 버전 표기를 뺌. 버전은 코드 안 상수(`PROMPT_VERSION`, `GUARDRAIL_VERSION` 등)로 실행 기록에 남고, 이전 버전은 git 태그로 보존
- 저장소 루트 경로를 `common/paths.py` 한 곳에서 정의 (기존에는 9개 파일이 각자 계산). 모델 digest·VRAM·프롬프트 지문 함수 3개를 `bench_v1/run_eval.py`에서 `common/ollama_runtime.py`로 옮김 (함수 본문은 그대로)
- `pyproject.toml`에 패키지 빌드 설정과 실행 명령 등록. `uv sync`가 패키지를 편집 가능 모드로 설치하고, 실행은 `uv run <명령>`
- 동작 동일성 확인: 테스트 173개, 저장된 v1.3 실행 기록 22건 재채점 결과 정리 전과 일치, 게이트 판정 결과 일치, 기록된 모델 응답을 재생한 실행 결과 일치(seed 1·11 각 64건), v1.0 벤치마크 실행 흐름·프롬프트 지문 일치, v1.0 산출물(`benchmark_summary.json`, `format_compliance.json`, 날조 탐지 결과) 일치

| 기존 경로 | 새 경로 | 실행 명령 |
| :--- | :--- | :--- |
| `src/run_eval_v2.py` | `src/triage_eval/pipeline/run.py` | `uv run triage-run` |
| `src/score_v2.py` | `src/triage_eval/pipeline/score.py` | `uv run triage-score` |
| `src/gate_v13.py` | `src/triage_eval/pipeline/gate.py` | `uv run triage-gate` |
| `src/contract_v2.py` | `src/triage_eval/pipeline/contract.py` | — |
| `src/prompt_v2.py` | `src/triage_eval/pipeline/prompt.py` | — |
| `src/guardrail_v2.py` | `src/triage_eval/pipeline/guardrail.py` | — |
| `src/run_eval.py` | `src/triage_eval/bench_v1/run_eval.py` | `uv run bench-run` |
| `src/compare_runs.py` | `src/triage_eval/bench_v1/compare_runs.py` | `uv run bench-gate` |
| `src/summarize_eval.py` | `src/triage_eval/bench_v1/summarize_eval.py` | `uv run bench-summarize` |
| `src/capture_env.py` | `src/triage_eval/bench_v1/capture_env.py` | `uv run bench-capture-env` |
| `src/score_format.py` | `src/triage_eval/common/score_format.py` | `uv run bench-score-format` |
| `src/detect_hallucination.py` | `src/triage_eval/common/detect_hallucination.py` | `uv run bench-hallucination` |
| `src/preflight.py` | `src/triage_eval/common/preflight.py` | — |
| `src/01_ollama_chat.py`, `02_luna_chat.py`, `test_fewshot.py` | `scripts/legacy/` | `uv run python scripts/legacy/<파일>` |
| `tests/test_contract_v2.py` 등 v1.3 테스트 5개 | `tests/test_pipeline_*.py` | — |

이 대응표보다 앞선 기록(위 1~3단계와 이전 버전)의 파일 경로는 당시 경로입니다.

### 최종 측정 (평가용 세트 31건 × 2회, 2026-10-02)
- 최종 구성(프롬프트 v2.3, 형식 재요청, 폐기 확인, 후처리 안전장치 g2)으로 평가용 세트를 1회 측정. 결과를 보고 프롬프트·안전장치·채점기를 고치지 않는다는 규칙을 측정 전에 정함
- Qwen2.5-7B (개발용 → 평가용): 허용 값 위반·출력 언어 위반·결함 폐기 0 → 0건, 형식 STRICT 100% → 100%, 처리 정답률 75.0% → 62.9%, 우선순위 정답률 62.5% → 43.5%, X-1 누락 2/22 → 6/18, X-3 누락 0/12 → 4/10, 6칸 모두 정답 28.1% → 8.1%
- 날조 2건은 탐지기 오탐("100번" → "100회")으로 판단, 측정값은 그대로 기록 ([ISSUE-008](docs/issue_log.md#issue-008), v1.4 수정)
- Llama3.1-8B: 형식 STRICT 50%, X-1 누락 18/18, 처리 정답률 30.6% — Qwen 선정 판단 유지
- 해석: 코드로 강제한 형식·절차는 일반화됐고, 모델 판단은 개발용 문항에 맞춰져 있었음 ([KL-003](docs/issue_log.md#kl-003)). 보고서: [`report/eval_v13_final.md`](report/eval_v13_final.md)

### 하지 않은 것
- 로드맵에 있던 "변형"(AI로 말투·오타 변형) 단계 — 63건 모두 사람이 검토한 원문만 사용

---

## [v1.2] — 2026-10-01

> **답하려는 질문:** 가장 위험한 결함(날조)을 사람 없이 잡을 수 있는가?

### 추가
- `src/detect_hallucination.py` — 응답의 [요약]·[누락 정보] 필드에서 입력에 근거 없는 구체 사실(OS·하드웨어·기기·버전·수치·조작 입력)을 규칙 기반으로 탐지. 정보를 요청하는 문맥("Windows 10/11 중 택1 확인 필요")은 날조로 세지 않음
  - 실제 로그 85건 검증: Llama Q08 날조 4건 전수 탐지, Qwen 40건·Cloud 5건 오탐 0건
- `src/preflight.py` — 실행 전 측정 환경 점검(Ollama 외 GPU 점유, 전원 연결)을 로그에 기록 ([OBS-001](docs/issue_log.md#obs-001))
- `run_eval.py --seed N` — seed 고정 모드 (1회차 N, 2회차 N+1). `--strict-env` — 측정 환경 경고가 있으면 실행하지 않음
- 합격 기준 `hallucination_max = 0` (절대), `verdict_change_max = 0` (같은 seed일 때만 적용, 아니면 SKIP)
- 테스트 38개 추가 (47 → 85): `test_detect_hallucination.py`, `test_preflight.py`, `test_run_eval.py`, `test_compare_runs.py` 보강
- README §4-7) 측정 환경 체크리스트와 seed 재현성 확인 방법

### 수정
- 환각 탐지기 오탐 2건을 출시 전 단위 테스트에서 발견해 수정 ([ISSUE-006](docs/issue_log.md#issue-006))

### 검증 (2026-10-01 실측)
- seed=1로 두 번 실행: 응답 원문 **40/40건 일치**, 판정 변화 0건 → `verdict_change_max = 0` 확정
- 첫 실행을 새 기본 기준선 `data/results/baseline/v1.2_seed1_local_eval_results.json`으로 고정 (v1.0 기준선은 README 수치의 출처로 보존)
- Llama Q08 날조는 seed가 다른 3번의 실행(v1.0, 9/30, 10/1)의 6회차 **전부에서** 재현됐고, 탐지기가 새 형태("3회 연속 패턴", "10분 정도 플레이 후")까지 탐지
- 깨끗한 측정 환경에서 Llama 평균 속도 64.3 t/s로 회복 (9/30 재실행 44.9 t/s) → 9/30 급락은 환경 탓이었다는 해석 뒷받침
- 테스트 85개 (기본 기준선의 seed 기록, 같은 seed 재실행 응답 일치를 테스트로 고정)

### 변경
- README §7 고도화 로드맵 재설계 — 최종 목표를 "사람이 보지 않아도 1차 트리아지가 돌아가는 파이프라인"으로 정하고, 최종 지표 4종(자동 처리율, 자동 처리분 정확도, 날조 0건, 위험 건 누락 0건)을 정의
  - v1.3: 현업 기반 평가셋 구축 방식(분류 체계 → 판정 기준서 → 시드 케이스 → 변형, 개발용/평가용 분리)과 실사용 시나리오 기록
  - v1.5 신설: 확신도 기반 라우팅(자동 등록 / QA 검토 큐)
  - v2.0: BTS 자동 인입(Redmine) + 중복 티켓 감지(RAG) + 무인 운영 데모

---

## [v1.1.1] — 2026-09-30

> **답하려는 질문:** 평가 도구 자체는 믿을 수 있는가?

### 추가
- `tests/` — 평가 도구 단위 테스트 47개 (pytest)
  - `test_score_format.py`: 포맷 규칙 R1~R6가 각자 자기 위반만 정확히 잡는지 확인. v1.0 로그를 채점했을 때 README의 준수율이 재현되는지 확인
  - `test_summarize_eval.py`: half-up 반올림, 워밍업 제외, 결측 속도 처리. v1.0 로그 집계가 README 성능 표와 같은지 확인
  - `test_compare_runs.py`: 게이트 판정(통과·실패·경계값), 비교 불가 조건, 기준 파일 오타 거부, 종료 코드 0/1/2
- `.github/workflows/tests.yml` — `main`에 push할 때마다 pytest 자동 실행 (GitHub Actions)
- README 테스트 배지, §4-6) 평가 도구 테스트 절

### 변경
- `run_eval.py` — 결과를 `data/results/history/`에만 저장하도록 변경. 문서 수치의 출처인 `local_eval_results.json`은 `--update-latest`를 줄 때만 교체 ([ISSUE-001](docs/issue_log.md#issue-001))
- `compare_runs.py` — 후보를 지정하지 않으면 `history/`에서 가장 최근 실행을 자동으로 선택

### 수정
- `compare_runs.py` — 허용폭과 정확히 같은 변화(+20%)가 부동소수점 오차로 FAIL 나던 경계값 결함 수정 ([ISSUE-002](docs/issue_log.md#issue-002))
- `compare_runs.py` — 합격 기준 파일에 모르는 섹션·키나 숫자가 아닌 값이 있으면 판정 불가(종료 코드 2)로 멈춤. 이전에는 오타 난 기준이 조용히 빠진 채 PASS가 났음 ([ISSUE-003](docs/issue_log.md#issue-003))
- CI — `astral-sh/setup-uv` 액션 버전을 존재하지 않던 `v9`에서 `v10.1.0`으로 수정 ([ISSUE-004](docs/issue_log.md#issue-004))

---

## [v1.1] — 2026-09-30

> **답하려는 질문:** 무언가 바꿨을 때 나빠졌는가?

### 추가
- `src/compare_runs.py` — 기준선과 후보 두 실행을 비교하는 회귀 게이트. 결과를 종료 코드로 반환 (0 PASS / 1 FAIL / 2 판정 불가)
- `gate_criteria.toml` — 합격 기준. 절대 기준(바닥선) 6개와 회귀 기준(허용 악화폭) 4개, 기준마다 근거 주석 포함
- `data/results/baseline/v1.0_local_eval_results.json` — README 수치의 출처인 v1.0 로그의 고정 사본
- `data/results/history/local_eval_results_20260930_154355.json` — v1.1 이후 첫 재실행 기록 (40회)
- `data/results/gate_result.json`, `report/regression_gate.md` — 첫 회귀 판정 결과: Qwen2.5-7B **PASS**, 판정 변화 3건
- README §4-5) 회귀 게이트, §7 고도화 로드맵

### 변경
- `run_eval.py` — 로그 `metadata.run_config`에 실행 조건 기록: 생성 옵션, 반복 횟수, 시스템 프롬프트·문항 파일의 SHA-256 지문, 모델 digest

### 수정
- README — 한국어 조사 앞에서 굵은 글씨가 깨지던 문제, 로드맵 표 칸 안 줄바꿈 정리 ([ISSUE-005](docs/issue_log.md#issue-005))

### 확인된 한계
- 첫 회귀 판정에서 **게이트가 잡지 못하는 결함 2건**이 확인됐습니다. v1.2의 근거입니다 ([KL-001](docs/issue_log.md#kl-001))

---

## [v1.0] — KANT 부트캠프 1차 프로젝트

> **답하려는 질문:** 어떤 모델이 이 업무에 맞는가?

- 로컬 LLM 2종(`qwen2.5:7b`, `llama3.1:8b`) × 10문항 × 2회 = 40회 본 실험, Cloud(`gpt-5.6-luna`) 대조 5회
- 포맷 준수율 자동 채점(R1~R6), 성능 지표 재집계, 실행 환경 실측 스크립트
- 결론: **Qwen2.5-7B 채택.** Llama-3.1-8B는 단문 리포트(Q08)에서 없는 결함과 PC 사양을 지어내 탈락
- 상세: [`report/final_selection.md`](report/final_selection.md)

[v1.2]: https://github.com/kokoball-eval/game-bug-triage-llm-eval/compare/v1.1.1...v1.2
[v1.1.1]: https://github.com/kokoball-eval/game-bug-triage-llm-eval/compare/v1.1...v1.1.1
[v1.1]: https://github.com/kokoball-eval/game-bug-triage-llm-eval/tree/v1.1
