# 변경 이력 (Changelog)

이 프로젝트의 버전별 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며, 각 버전이 **어떤 질문에 답하기 위해** 만들어졌는지를 함께 적습니다.
진행 중 발견한 결함과 조치 내역은 [`docs/issue_log.md`](docs/issue_log.md)에 따로 기록합니다.

---

## [v1.3] — 진행 중

> **답하려는 질문:** 평가셋이 실제 현업 인입을 대표하는가?

### 추가 (1단계: 평가셋)
- `data/eval_v13/aether_raid_v13.json` — 현업 기반 평가셋 63건 (대표 세트 40: 트랙 A 커뮤니티 원문 20 + 트랙 B QA 작성 이슈 20 / 집중 세트 23: 운영 불만형·경계 사례·감정 속 진짜 결함·확인 필요·거짓 경보)
  - 정답 라벨 7종(분류·우선순위·모듈·재현 정보·발생 빈도·처리·사람 검토)과 위험 건 측정 표시(X-1~X-3), 반드시 요청할 정보·권장 조치
  - 개발용/평가용 분할 (대표 20/20, 집중 12/11 — 위험 건 측정 문항을 먼저 번갈아 배정)
- `docs/dataset/` — 판정 기준서, 문항 설계안, 설계 인터뷰 기록 4회, 검토 기록(배치 검토 5회 + 전체 검토 5회의 쟁점·판단·반영)
- `tools/dataset_v13/` — 배치별 생성 스크립트(정답 라벨의 원본), 병합·분할·검증(`merge_dataset.py`), 검토 문서 렌더러
- `tests/test_dataset_v13.py` — 저장소의 JSON이 생성 스크립트 결과와 같은지, 라벨 규칙 간 일관성 검사가 오류를 잡는지, 분할이 균형인지 (테스트 85 → 92)

### 판정 체계 변경 (v1.0 10문항·출력 형식은 그대로 보존)
- `[심각도]` → `[우선순위]` (Critical / Major / Minor / Trivial / 판단보류 / 해당 없음) — 실무는 심각도 대신 우선순위 4단계를 썼음
- `[재현 여부]` → `[재현 정보]`(충분 / 부족) + `[발생 빈도]`(항상 / 간헐적 / 1회 / 미기재 / 해당 없음) — 모델은 재현 성공 여부를 알 수 없으므로, 리포트에 적힌 빈도만 옮김
- `[분류]`, `[처리]` 신설 — 처리 6종 중 `긴급 사인 요청`은 Critical을 리드 QA 사인 후 개발에 전달한다는 뜻 (자동화가 Critical을 직접 보내지 않음)

### 하지 않은 것
- 로드맵에 있던 "변형"(AI로 말투·오타 변형) 단계 — 63건 모두 사람이 검토한 원문만 사용



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
