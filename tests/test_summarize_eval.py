"""summarize_eval.py 집계 정의 테스트.

README 표의 성능 수치(지연·속도·토큰)가 원본 로그에서 그대로 재계산되는지,
반올림 규칙이 문서 표기와 같은지를 고정한다.
"""

import pytest

from triage_eval.bench_v1.summarize_eval import aggregate_local, rnd


@pytest.mark.parametrize("value, digits, expected", [
    (117.55, 1, 117.6),   # 파이썬 기본 round()는 117.5 로 내려서 문서와 어긋난다
    (2.675, 2, 2.68),     # 이진 부동소수점으로는 2.67499... 이라 round()가 2.67을 낸다
    (1.3895, 3, 1.39),
    (0.0, 2, 0.0),
])
def test_rnd_rounds_half_up(value, digits, expected):
    assert rnd(value, digits) == expected


def test_rnd_keeps_missing_value_as_none():
    """결측은 결측으로 남아야 한다. 0으로 바뀌면 '속도 0'이라는 거짓 측정값이 된다."""
    assert rnd(None, 2) is None


def test_aggregate_local_reproduces_readme_table(baseline):
    out = aggregate_local(baseline)
    qwen, llama = out["qwen2.5:7b"], out["llama3.1:8b"]

    assert (qwen["n"], qwen["success"]) == (20, 20)
    assert qwen["latency_sec"] == 1.39
    assert qwen["tokens_per_sec"] == 57.68
    assert qwen["eval_count"] == 76.4

    assert llama["latency_sec"] == 1.809
    assert llama["tokens_per_sec"] == 66.56
    assert llama["eval_count"] == 117.6


def test_warmup_runs_are_excluded(baseline):
    """워밍업이 본 통계에 섞이면 먼저 호출한 모델이 느려 보인다."""
    before = aggregate_local(baseline)["qwen2.5:7b"]
    slow_warmup = dict(baseline["results"][0], is_warmup=True, elapsed_sec=999.0)
    baseline["results"].append(slow_warmup)
    after = aggregate_local(baseline)["qwen2.5:7b"]
    assert after["n"] == before["n"]
    assert after["latency_sec"] == before["latency_sec"]


def test_missing_speed_is_skipped_not_zeroed(baseline):
    """tokens_per_sec 가 None 인 회차는 평균에서 빠져야 한다 (0으로 넣으면 평균이 무너짐)."""
    qwen_rows = [r for r in baseline["results"] if r["model"] == "qwen2.5:7b"]
    qwen_rows[0]["tokens_per_sec"] = None
    out = aggregate_local(baseline)["qwen2.5:7b"]
    assert out["tokens_per_sec_n"] == 19
    assert out["tokens_per_sec"] > 50        # 0이 섞였다면 크게 떨어진다
