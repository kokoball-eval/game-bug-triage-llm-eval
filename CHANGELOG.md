# 변경 이력 (Changelog)

이 프로젝트의 버전별 변경 사항을 기록합니다.
형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따르며, 각 버전이 **어떤 질문에 답하기 위해** 만들어졌는지를 함께 적습니다.
진행 중 발견한 결함과 조치 내역은 [`docs/issue_log.md`](docs/issue_log.md)에 따로 기록합니다.

---

## [Unreleased]

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

[v1.1.1]: https://github.com/kokoball-eval/game-bug-triage-llm-eval/compare/v1.1...v1.1.1
[v1.1]: https://github.com/kokoball-eval/game-bug-triage-llm-eval/tree/v1.1
