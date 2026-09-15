# 포맷 계약 준수율 채점 근거 (Format Contract Audit Trail)

> 본 문서는 `src/score_format.py`가 원본 응답 로그(`data/results/local_eval_results.json`, `cloud_eval_results.json`)를
> 기계적으로 재채점한 결과입니다. 수치를 눈으로 세지 않고 스크립트로 산출하므로, 아래 표의 모든 판정은
> `uv run python src/score_format.py` 재실행으로 그대로 재현됩니다. 원본 데이터는 `data/results/format_compliance.json`.

## 1. 채점 규칙

| 규칙 | 내용 |
| :--- | :--- |
| `R1_no_preamble` | 응답이 '[요약]:'으로 즉시 시작 (서두 사족 없음) |
| `R2_all_fields` | 5개 필드 라벨 전부 존재 |
| `R3_field_order` | 필드 순서가 규격과 일치 |
| `R4_no_blank_line` | 필드 사이 빈 줄 없음 |
| `R5_no_stray_text` | 필드 라벨이 아닌 줄이 중간에 끼어들지 않음 |
| `R6_enum_valid` | [심각도]/[재현 여부] 값이 지정된 선택지에 포함 |

* **STRICT**: R1~R6 전부 통과 — 후처리 없이 그대로 파싱 가능한 완전 규격 준수
* **PARSABLE**: R4(빈 줄 금지)를 제외한 전 규칙 통과 — 줄 단위 파서가 빈 줄을 건너뛰면 안전하게 파싱 가능한 수준
* 심각도 Enum: Blocker, Critical, Major, Minor, Trivial, 판단보류
* 재현 여부 Enum: 간헐적, 발생(100%), 불명확, 재현 불가

## 2. 집계 결과

| 모델 | 표본(n) | STRICT | PARSABLE | 실패 규칙 |
| :--- | :---: | :---: | :---: | :--- |
| `qwen2.5:7b` | 20 | **20/20 (100%)** | 20/20 (100%) | 없음 |
| `llama3.1:8b` | 20 | **1/20 (5%)** | 20/20 (100%) | `R4_no_blank_line` 19건 |
| `gpt-5.6-luna` | 5 | **5/5 (100%)** | 5/5 (100%) | 없음 |

### Cloud 공통 5문항 부분집합 (Q01, Q02, Q06, Q08, Q10)

| 모델 | 표본(n) | STRICT | PARSABLE |
| :--- | :---: | :---: | :---: |
| `qwen2.5:7b` | 10 | **10/10 (100%)** | 10/10 (100%) |
| `llama3.1:8b` | 10 | **0/10 (0%)** | 10/10 (100%) |
| `gpt-5.6-luna` | 5 | **5/5 (100%)** | 5/5 (100%) |

## 3. 핵심 해석

1. **사족(preamble)은 전 회차 0건**: 45건 전수에서 `R1_no_preamble` 실패가 단 1건도 없었습니다. 즉 2일차 본 실험에서는
   두 로컬 모델 모두 대화형 서두를 출력하지 않았으며, 1일차 스모크 테스트에서 관측된 Llama의 `"다음은 분석된..."` 서두는
   **본 실험과 다른 프롬프트(3줄 요약 형식)에서 발생한 것**으로, 네거티브 가드레일 주입 이후에는 재현되지 않았습니다.
2. **Llama의 유일한 실패 요인은 필드 사이 빈 줄(`R4`) 19/20건**: 필드 누락·순서 오류·잉여 텍스트·Enum 위반은 0건입니다.
   따라서 Llama의 포맷 문제는 '계약 위반'이 아니라 '개행 스타일'의 문제로 한정됩니다.
3. **출력 스타일의 회차 간 흔들림**: Llama 20회 중 `llama3.1_8b_Q05_run2` 단 1회만 빈 줄 없이 출력되어 STRICT를 통과했습니다.
   동일 프롬프트·동일 설정에서도 개행 스타일이 일관되지 않는다는 점은 파서 전처리(빈 줄 정규화)가 필요하다는 근거가 됩니다.
4. **Qwen과 Cloud는 STRICT 100%**: 두 모델은 빈 줄 없이 5개 필드를 순서대로, Enum 범위 안에서 출력했습니다.

## 4. 회차별 판정 상세

| eval_id | 모델 | 문항 | 회차 | STRICT | PARSABLE | 실패 규칙 및 사유 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `qwen2.5_7b_Q01_run1` | `qwen2.5:7b` | Q01 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q02_run1` | `qwen2.5:7b` | Q02 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q03_run1` | `qwen2.5:7b` | Q03 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q04_run1` | `qwen2.5:7b` | Q04 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q05_run1` | `qwen2.5:7b` | Q05 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q06_run1` | `qwen2.5:7b` | Q06 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q07_run1` | `qwen2.5:7b` | Q07 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q08_run1` | `qwen2.5:7b` | Q08 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q09_run1` | `qwen2.5:7b` | Q09 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q10_run1` | `qwen2.5:7b` | Q10 | 1 | ✅ | ✅ | — |
| `qwen2.5_7b_Q01_run2` | `qwen2.5:7b` | Q01 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q02_run2` | `qwen2.5:7b` | Q02 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q03_run2` | `qwen2.5:7b` | Q03 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q04_run2` | `qwen2.5:7b` | Q04 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q05_run2` | `qwen2.5:7b` | Q05 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q06_run2` | `qwen2.5:7b` | Q06 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q07_run2` | `qwen2.5:7b` | Q07 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q08_run2` | `qwen2.5:7b` | Q08 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q09_run2` | `qwen2.5:7b` | Q09 | 2 | ✅ | ✅ | — |
| `qwen2.5_7b_Q10_run2` | `qwen2.5:7b` | Q10 | 2 | ✅ | ✅ | — |
| `llama3.1_8b_Q01_run1` | `llama3.1:8b` | Q01 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q02_run1` | `llama3.1:8b` | Q02 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q03_run1` | `llama3.1:8b` | Q03 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q04_run1` | `llama3.1:8b` | Q04 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q05_run1` | `llama3.1:8b` | Q05 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q06_run1` | `llama3.1:8b` | Q06 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q07_run1` | `llama3.1:8b` | Q07 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q08_run1` | `llama3.1:8b` | Q08 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q09_run1` | `llama3.1:8b` | Q09 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q10_run1` | `llama3.1:8b` | Q10 | 1 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q01_run2` | `llama3.1:8b` | Q01 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q02_run2` | `llama3.1:8b` | Q02 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q03_run2` | `llama3.1:8b` | Q03 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q04_run2` | `llama3.1:8b` | Q04 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q05_run2` | `llama3.1:8b` | Q05 | 2 | ✅ | ✅ | — |
| `llama3.1_8b_Q06_run2` | `llama3.1:8b` | Q06 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q07_run2` | `llama3.1:8b` | Q07 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q08_run2` | `llama3.1:8b` | Q08 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q09_run2` | `llama3.1:8b` | Q09 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `llama3.1_8b_Q10_run2` | `llama3.1:8b` | Q10 | 2 | ❌ | ✅ | `R4_no_blank_line`: 빈 줄 4개 (줄번호 [1, 3, 5, 7]) |
| `cloud_luna_Q01` | `gpt-5.6-luna` | Q01 | 1 | ✅ | ✅ | — |
| `cloud_luna_Q02` | `gpt-5.6-luna` | Q02 | 1 | ✅ | ✅ | — |
| `cloud_luna_Q06` | `gpt-5.6-luna` | Q06 | 1 | ✅ | ✅ | — |
| `cloud_luna_Q08` | `gpt-5.6-luna` | Q08 | 1 | ✅ | ✅ | — |
| `cloud_luna_Q10` | `gpt-5.6-luna` | Q10 | 1 | ✅ | ✅ | — |
