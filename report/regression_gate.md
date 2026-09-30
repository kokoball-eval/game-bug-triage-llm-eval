# 회귀 게이트 판정 결과 (Regression Gate)

> `src/compare_runs.py` 자동 생성 · 판정 시각 2026-09-30T15:47:53.250473
> 기준선: `data/results/baseline/v1.0_local_eval_results.json`
> 후보: `data/results/history/local_eval_results_20260930_154355.json`
> 합격 기준: `gate_criteria.toml` (v1.1)

## 종합 판정: **PASS**

## `qwen2.5:7b` — ✅ PASS

> ⚠️ 기준선 로그에 run_config 가 없습니다 (v1.0 이전 형식). 생성 옵션·프롬프트가 같은지 코드로 검증하지 못했습니다.

| 지표 | 기준선 | 후보 |
| :--- | ---: | ---: |
| 표본 수 | 20 | 20 |
| 호출 성공률(%) | 100.0 | 100.0 |
| STRICT 준수율(%) | 100.0 | 100.0 |
| PARSABLE 준수율(%) | 100.0 | 100.0 |
| R1 서두 사족(건) | 0 | 0 |
| R6 enum 이탈(건) | 0 | 0 |
| 평균 지연(초) | 1.39 | 1.516 |
| 평균 속도(t/s) | 57.68 | 55.48 |
| 평균 생성 토큰 | 76.4 | 79.9 |

| 판정 | 구분 | 기준 | 내용 |
| :---: | :---: | :--- | :--- |
| ✅ | 절대 | `success_rate_min` | 100.0 ≥ 100.0 이어야 함 |
| ✅ | 절대 | `strict_rate_min` | 100.0 ≥ 95.0 이어야 함 |
| ✅ | 절대 | `parsable_rate_min` | 100.0 ≥ 100.0 이어야 함 |
| ✅ | 절대 | `preamble_fail_max` | 0 ≤ 0 이어야 함 |
| ✅ | 절대 | `enum_fail_max` | 0 ≤ 0 이어야 함 |
| ✅ | 절대 | `latency_sec_max` | 1.516 ≤ 2.0 이어야 함 |
| ✅ | 회귀 | `strict_rate_drop_max_pp` | 변화 +0.0%p (허용 악화폭 5.0%p) |
| ✅ | 회귀 | `latency_increase_max_pct` | 변화 +9.1% (허용 악화폭 20.0%) |
| ✅ | 회귀 | `tokens_per_sec_drop_max_pct` | 변화 -3.8% (허용 악화폭 15.0%) |
| ✅ | 회귀 | `eval_count_increase_max_pct` | 변화 +4.6% (허용 악화폭 30.0%) |

**판정 변화 (참고용, 합격 기준 아님): 3건**

> v1.0은 seed 미고정이라 같은 조건에서도 판정이 흔들립니다. v1.2 seed 고정 후 합격 기준으로 승격 예정입니다.

| 문항 | 회차 | 변화 |
| :---: | :---: | :--- |
| Q07 | 1 | 재현 여부: `불명확` → `발생(100%)` |
| Q07 | 2 | 모듈: `그래픽` → `시스템` |
| Q08 | 1 | 모듈: `시스템` → `네트워크`<br>심각도: `Critical` → `Blocker` |

