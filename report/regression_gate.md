# 회귀 게이트 판정 결과 (Regression Gate)

> `src/compare_runs.py` 자동 생성 · 판정 시각 2026-10-01T10:05:14.632111
> 기준선: `data/results/baseline/v1.2_seed1_local_eval_results.json`
> 후보: `data/results/history/local_eval_results_20261001_100030.json`
> 합격 기준: `gate_criteria.toml` (v1.2)

## 종합 판정: **PASS**

## `qwen2.5:7b` — ✅ PASS

| 지표 | 기준선 | 후보 |
| :--- | ---: | ---: |
| 표본 수 | 20 | 20 |
| 호출 성공률(%) | 100.0 | 100.0 |
| STRICT 준수율(%) | 100.0 | 100.0 |
| PARSABLE 준수율(%) | 100.0 | 100.0 |
| R1 서두 사족(건) | 0 | 0 |
| R6 enum 이탈(건) | 0 | 0 |
| 날조 응답(건) | 0 | 0 |
| 평균 지연(초) | 1.471 | 1.448 |
| 평균 속도(t/s) | 55.51 | 56.2 |
| 평균 생성 토큰 | 76.8 | 76.8 |

| 판정 | 구분 | 기준 | 내용 |
| :---: | :---: | :--- | :--- |
| ✅ | 절대 | `success_rate_min` | 100.0 ≥ 100.0 이어야 함 |
| ✅ | 절대 | `strict_rate_min` | 100.0 ≥ 95.0 이어야 함 |
| ✅ | 절대 | `parsable_rate_min` | 100.0 ≥ 100.0 이어야 함 |
| ✅ | 절대 | `preamble_fail_max` | 0 ≤ 0 이어야 함 |
| ✅ | 절대 | `enum_fail_max` | 0 ≤ 0 이어야 함 |
| ✅ | 절대 | `latency_sec_max` | 1.448 ≤ 2.0 이어야 함 |
| ✅ | 절대 | `hallucination_max` | 0 ≤ 0 이어야 함 |
| ✅ | 회귀 | `strict_rate_drop_max_pp` | 변화 +0.0%p (허용 악화폭 5.0%p) |
| ✅ | 회귀 | `latency_increase_max_pct` | 변화 -1.6% (허용 악화폭 20.0%) |
| ✅ | 회귀 | `tokens_per_sec_drop_max_pct` | 변화 +1.2% (허용 악화폭 15.0%) |
| ✅ | 회귀 | `eval_count_increase_max_pct` | 변화 +0.0% (허용 악화폭 30.0%) |
| ✅ | 회귀 | `verdict_change_max` | 같은 seed 에서 판정 변화 0건 ≤ 0 이어야 함 |

**판정 변화 목록: 0건**

> 두 실행이 같은 seed로 돌았으므로 판정 변화는 합격 기준(`verdict_change_max`)으로 판정했습니다.


