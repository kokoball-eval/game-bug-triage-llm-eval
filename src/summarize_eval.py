"""
본 실험(2일차) 및 Cloud 대조군(3일차) 성능 지표 재집계 스크립트.

README와 report/*.md에 기재된 성능 수치를 원본 로그에서 다시 계산해 출력한다.
문서에 적힌 값과 이 스크립트의 출력이 일치해야 한다.

입력 (읽기 전용):
    data/results/local_eval_results.json   - 2일차 로컬 40회 본 실험
    data/results/cloud_eval_results.json   - 3일차 Cloud 5회 대조 실험
출력:
    data/results/benchmark_summary.json    - 집계 결과
    표준 출력                                - 문서 대조용 표

[집계 규칙]
1. 워밍업(is_warmup=True)은 본 통계에서 제외한다. 워밍업은 '로딩 시간'만 별도로 보고한다.
2. 평균 토큰 생성 속도는 회차별 tokens_per_sec의 단순 평균이다.
   (총토큰/총생성시간의 가중 평균이 아니다. 두 값은 다르므로 정의를 고정한다.)
3. tokens_per_sec가 None인 회차는 속도 집계에서만 제외한다. 0으로 대체하지 않는다.
4. Cloud 공통 문항 서브셋은 레코드의 cloud_eval 플래그로 판별한다.
   Cloud와 1:1 비교하는 표는 반드시 이 서브셋 값을 써야 한다(10문항 전체 평균과 다름).
"""

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import mean


def rnd(value, digits):
    """금융권 반올림(은행가 반올림)이 아닌 일반 반올림(half-up)을 쓴다.

    파이썬 기본 round()는 117.55를 117.5로 내리므로 문서 표기와 어긋난다.
    """
    if value is None:
        return None
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))

MODELS = ["qwen2.5:7b", "llama3.1:8b"]


def aggregate_local(payload: dict) -> dict:
    formal = [r for r in payload["results"] if not r.get("is_warmup")]
    warmups = {w["model"]: w for w in payload.get("warmup_runs", [])}

    out = {}
    for model in MODELS:
        rows = [r for r in formal if r["model"] == model]
        if not rows:
            continue
        speeds = [r["tokens_per_sec"] for r in rows if r["tokens_per_sec"] is not None]
        subset = [r for r in rows if r.get("cloud_eval")]
        vrams = [r["vram_mib"] for r in rows if r["vram_mib"]]
        warm = warmups.get(model)

        out[model] = {
            "n": len(rows),
            "success": sum(1 for r in rows if r["success"]),
            "latency_sec": rnd(mean(r["elapsed_sec"] for r in rows), 3),
            "tokens_per_sec": rnd(mean(speeds), 2) if speeds else None,
            "tokens_per_sec_n": len(speeds),
            "eval_count": rnd(mean(r["eval_count"] for r in rows), 1),
            "vram_mib": max(set(vrams), key=vrams.count) if vrams else None,
            "warmup_load_sec": warm["load_duration_sec"] if warm else None,
            "warmup_elapsed_sec": warm["elapsed_sec"] if warm else None,
            "cloud_subset": {
                "n": len(subset),
                "question_ids": sorted({r["question_id"] for r in subset}),
                "latency_sec": rnd(mean(r["elapsed_sec"] for r in subset), 3),
                "eval_count": rnd(mean(r["eval_count"] for r in subset), 1),
            },
        }
    return out


def aggregate_cloud(payload) -> dict:
    rows = payload["results"] if isinstance(payload, dict) else payload
    lat = [r["elapsed_sec"] for r in rows if r.get("elapsed_sec")]
    inp = sum(r.get("input_tokens") or 0 for r in rows)
    outp = sum(r.get("output_tokens") or 0 for r in rows)
    return {
        "n": len(rows),
        "latency_sec": rnd(mean(lat), 3) if lat else None,
        "input_tokens_total": inp,
        "output_tokens_total": outp,
        "output_tokens_avg": rnd(outp / len(rows), 1) if rows else None,
    }


def main():
    root = Path(__file__).resolve().parent.parent
    results_dir = root / "data" / "results"

    with (results_dir / "local_eval_results.json").open(encoding="utf-8") as f:
        local = aggregate_local(json.load(f))
    with (results_dir / "cloud_eval_results.json").open(encoding="utf-8") as f:
        cloud = aggregate_cloud(json.load(f))

    summary = {"local": local, "cloud": cloud}
    out_file = results_dir / "benchmark_summary.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    q, l = local["qwen2.5:7b"], local["llama3.1:8b"]

    print("=== 본 실험 집계 (10문항 × 2회, 워밍업 제외) ===")
    print(f"{'지표':<24}{'Qwen2.5-7B':>16}{'Llama-3.1-8B':>16}")
    print("-" * 56)
    rows = [
        ("표본 수 (n)", q["n"], l["n"]),
        ("호출 성공", f"{q['success']}/{q['n']}", f"{l['success']}/{l['n']}"),
        ("평균 지연 (초)", f"{q['latency_sec']:.3f}", f"{l['latency_sec']:.3f}"),
        ("평균 속도 (tokens/s)", q["tokens_per_sec"], l["tokens_per_sec"]),
        ("평균 생성 토큰", q["eval_count"], l["eval_count"]),
        ("VRAM 점유 (MiB)", q["vram_mib"], l["vram_mib"]),
        ("워밍업 로딩 (초)", q["warmup_load_sec"], l["warmup_load_sec"]),
    ]
    for label, a, b in rows:
        print(f"{label:<24}{str(a):>16}{str(b):>16}")

    qs, ls = q["cloud_subset"], l["cloud_subset"]
    print(f"\n=== Cloud 공통 문항 서브셋 {qs['question_ids']} ===")
    print(f"{'지표':<24}{'Qwen2.5-7B':>16}{'Llama-3.1-8B':>16}")
    print("-" * 56)
    print(f"{'표본 수 (n)':<24}{qs['n']:>16}{ls['n']:>16}")
    print(f"{'평균 지연 (초)':<24}{qs['latency_sec']:>16.3f}{ls['latency_sec']:>16.3f}")
    print(f"{'평균 생성 토큰':<24}{qs['eval_count']:>16}{ls['eval_count']:>16}")

    print(f"\n=== Cloud 대조군 (gpt-5.6-luna) ===")
    print(f"표본 수 (n)         {cloud['n']}")
    print(f"평균 지연 (초)      {cloud['latency_sec']}")
    print(f"입력 토큰 합        {cloud['input_tokens_total']}")
    print(f"출력 토큰 합        {cloud['output_tokens_total']}")
    print(f"평균 출력 토큰      {cloud['output_tokens_avg']}")

    print("\n=== 문서 기재용 파생 수치 ===")
    print(f"TPS 우위 (Llama/Qwen)     {l['tokens_per_sec'] / q['tokens_per_sec']:.3f}배"
          f"  → 약 {(l['tokens_per_sec'] / q['tokens_per_sec'] - 1) * 100:.0f}% 빠름")
    print(f"토큰 소모 배수 (Llama/Qwen) {l['eval_count'] / q['eval_count']:.2f}배")
    print(f"지연 우위 (Qwen)          {(1 - q['latency_sec'] / l['latency_sec']) * 100:.1f}% 신속")
    print(f"Cloud 대비 지연 배수       {cloud['latency_sec'] / qs['latency_sec']:.2f}배 (동일 5문항 기준)")
    print(f"VRAM 차이                 {l['vram_mib'] - q['vram_mib']:.1f} MiB")

    print(f"\n집계 결과 저장: {out_file.resolve()}")


if __name__ == "__main__":
    main()
