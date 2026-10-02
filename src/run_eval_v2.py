"""v1.3 평가셋(data/eval_v13/aether_raid_v13.json) 실행 스크립트 — 출력 형식 v2.

사용법:
    uv run python src/run_eval_v2.py --seed 1 --strict-env                 # 개발용(dev) 전체, Qwen·Llama
    uv run python src/run_eval_v2.py --seed 1 --model qwen2.5:7b           # 모델 하나만
    uv run python src/run_eval_v2.py --seed 1 --set focused                # 집중 세트만
    uv run python src/run_eval_v2.py --seed 1 --split test --final         # 평가용(test) — 최종 측정 때만

출력:
    data/results/v13/history/v13_<split>_<시각>.json   실행 기록 (항상 새 파일)

채점: uv run python src/score_v2.py

[설계 의도]
1. 기본 대상은 개발용(dev)이다. 평가용(test)은 --final 을 함께 줘야만 실행된다.
   프롬프트를 고치면서 test 점수를 보면, test에 맞춰 프롬프트를 고치게 되어 최종 수치를 믿을 수 없게 된다.
   "실수로 test를 돌리는 일"을 사람의 주의가 아니라 실행 조건으로 막는다.
2. 모델 호출 방식(generate + 문자열 결합, 워밍업 분리, 실패 시 다음 문항 진행)과
   실행 조건 기록(run_config), 측정 환경 점검은 v1 run_eval.py 와 같다.
   지문·digest·VRAM 측정 같은 공용 함수는 run_eval.py 에서 가져오되, run_eval.py 자체는 수정하지 않는다.
   v1 로그 형식이 바뀌면 v1 기준선과의 회귀 비교가 흔들리기 때문이다. v2에서 추가로 필요한
   입력 토큰 수(prompt_eval_count) 기록은 이 파일의 generate_once() 에서 한다.
3. num_ctx 를 8192로 명시한다. v2 프롬프트는 판정 규칙이 들어가 v1보다 길어서(약 3,000자),
   기본값 4,096 토큰에 출력까지 더하면 넘칠 수 있다. Ollama는 넘친 앞부분을 조용히 잘라 내므로,
   잘린 채 실행되면 "규칙을 못 지킨 모델"로 잘못 측정된다. 회차마다 입력 토큰 수(prompt_eval_count)를 기록하고,
   입력+출력 상한이 num_ctx 를 넘을 수 있으면 경고한다.
4. num_predict 를 512로 둔다. v2는 필드가 8개라 v1(350)보다 출력이 길다.
   잘린 응답은 형식 채점에서 R2(필드 누락)로 드러나므로, 상한에 걸린 회차 수도 기록한다.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import time

import ollama

from preflight import snapshot as preflight_snapshot
from prompt_v2 import SYSTEM_PROMPT_V2, build_prompt
from run_eval import get_model_digests, get_vram_mib, sha256_text

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "eval_v13" / "aether_raid_v13.json"
OUT_DIR = ROOT / "data" / "results" / "v13" / "history"

MODELS = ["qwen2.5:7b", "llama3.1:8b"]
REPEAT_COUNT = 2
OPTIONS_V2 = {"temperature": 0.2, "num_predict": 512, "num_ctx": 8192}


def rel(path: Path) -> str:
    """저장소 안이면 상대 경로, 밖이면(테스트 임시 폴더 등) 그대로 표시한다."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def select_items(dataset: dict, split: str, set_name: str) -> list[dict]:
    items = dataset["items"]
    if split != "all":
        items = [i for i in items if i["split"] == split]
    if set_name != "all":
        items = [i for i in items if i["set"] == set_name]
    return items


def generate_once(client, model: str, prompt: str, options: dict) -> dict:
    """완성된 프롬프트로 1회 생성한다. 측정 항목은 v1 execute_single_inference 와 같고 입력 토큰 수가 추가된다."""
    start = time.perf_counter()
    try:
        r = client.generate(model=model, prompt=prompt, options=options)
        eval_ns = r.get("eval_duration", 0)
        return {
            "success": True,
            "response_text": r.get("response", "").strip(),
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "load_duration_sec": round(r.get("load_duration", 0) / 1e9, 3),
            "prompt_eval_count": r.get("prompt_eval_count"),
            "eval_count": r.get("eval_count", 0),
            "tokens_per_sec": round(r.get("eval_count", 0) / (eval_ns / 1e9), 2) if eval_ns > 0 else None,
            "vram_mib": get_vram_mib(client, model),
            "error_message": None,
        }
    except Exception as e:  # 한 건 실패로 배치 전체가 멈추지 않게 기록하고 넘어간다
        return {
            "success": False, "response_text": "", "elapsed_sec": round(time.perf_counter() - start, 3),
            "load_duration_sec": 0.0, "prompt_eval_count": None, "eval_count": 0, "tokens_per_sec": None,
            "vram_mib": get_vram_mib(client, model), "error_message": str(e),
        }


def check_split_guard(split: str, final: bool) -> str | None:
    """설계 의도 1 — test 가 포함된 실행은 --final 이 있어야 한다. 막을 때는 이유를 돌려준다."""
    if split in ("test", "all") and not final:
        return ("평가용(test) 문항은 최종 측정 때만 실행합니다. 프롬프트 개선은 --split dev 로 하고, "
                "최종 측정이면 --final 을 함께 주세요.")
    return None


def options_for(seed_base: int | None, run_idx: int) -> dict:
    return dict(OPTIONS_V2) if seed_base is None else {**OPTIONS_V2, "seed": seed_base + run_idx - 1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v1.3 평가셋 실행 (출력 형식 v2)")
    p.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    p.add_argument("--set", dest="set_name", choices=["representative", "focused", "all"], default="all")
    p.add_argument("--model", action="append", help="실행할 모델 (여러 번 지정 가능, 기본: Qwen·Llama)")
    p.add_argument("--seed", type=int, default=None, help="seed 고정 모드 (1회차 N, 2회차 N+1)")
    p.add_argument("--repeat", type=int, default=REPEAT_COUNT)
    p.add_argument("--strict-env", action="store_true", help="측정 환경 경고가 있으면 실행하지 않음")
    p.add_argument("--final", action="store_true", help="평가용(test) 문항 실행 허용 — 최종 측정 때만")
    args = p.parse_args(argv)

    blocked = check_split_guard(args.split, args.final)
    if blocked:
        print(blocked)
        return 2

    dataset_text = DATASET.read_text(encoding="utf-8")
    dataset = json.loads(dataset_text)
    items = select_items(dataset, args.split, args.set_name)
    models = args.model or MODELS
    client = ollama.Client()

    environment = preflight_snapshot(client)
    print("=== 측정 환경 점검 ===")
    for w in environment["warnings"]:
        print(f"  ⚠️  {w}")
    if environment["warnings"] and args.strict_env:
        print("--strict-env: 측정 환경 경고가 있어 실행하지 않습니다.")
        return 2
    if not environment["warnings"]:
        print("  ✅ 경고 없음")

    seeds = None if args.seed is None else {str(i): args.seed + i - 1 for i in range(1, args.repeat + 1)}
    run_config = {
        "contract": "v2",
        "options": OPTIONS_V2,
        "repeat_count": args.repeat,
        "split": args.split,
        "set": args.set_name,
        "system_prompt_sha256": sha256_text(SYSTEM_PROMPT_V2),
        "dataset_sha256": hashlib.sha256(json.dumps(dataset, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "item_ids": [i["id"] for i in items],
        "model_digests": get_model_digests(client, models),
        "seeds": seeds,
        "environment": environment,
    }
    total = len(models) * len(items) * args.repeat
    print(f"\n=== {len(models)}개 모델 × {len(items)}문항({args.split}/{args.set_name}) × {args.repeat}회 = {total}회 ===")

    results, warmups = [], []
    for model in models:
        w = generate_once(client, model, SYSTEM_PROMPT_V2 + "\n[리포트]\n워밍업 입력", options_for(args.seed, 1))
        warmups.append({"model": model, "is_warmup": True, **w})
        print(f"[{model}] 워밍업 {w['elapsed_sec']}s (로드 {w['load_duration_sec']}s)")
        for run_idx in range(1, args.repeat + 1):
            opts = options_for(args.seed, run_idx)
            for n, item in enumerate(items, start=1):
                prompt = build_prompt(item)
                res = generate_once(client, model, prompt, opts)
                near_limit = (res.get("prompt_eval_count") or 0) + OPTIONS_V2["num_predict"] > OPTIONS_V2["num_ctx"]
                results.append({
                    "eval_id": f"{model.replace(':', '_')}_{item['id']}_run{run_idx}",
                    "model": model, "run_index": run_idx, "item_id": item["id"],
                    "set": item["set"], "track": item["track"], "split": item["split"],
                    "seed": opts.get("seed"), "timestamp": datetime.now().isoformat(),
                    "hit_num_predict": res.get("eval_count", 0) >= OPTIONS_V2["num_predict"],
                    "context_near_limit": near_limit,
                    **res,
                })
                status = "성공" if res["success"] else f"실패 - {res['error_message']}"
                print(f"[{model}] [Run {run_idx}] ({n}/{len(items)}) {item['id']}: {status} "
                      f"({res['elapsed_sec']}s, 입력 {res.get('prompt_eval_count')} 토큰)")

    payload = {
        "metadata": {
            "project": dataset["name"], "dataset_version": dataset["version"],
            "executed_at": datetime.now().isoformat(), "models": models,
            "total_formal_runs": len(results), "warmup_runs": len(warmups), "run_config": run_config,
        },
        "warmup_runs": warmups,
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"v13_{args.split}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    near = sum(r["context_near_limit"] for r in results)
    capped = sum(r["hit_num_predict"] for r in results)
    print(f"\n=== 완료: {len(results)}회 → {rel(out)}")
    if near:
        print(f"  ⚠️  입력+출력 상한이 num_ctx 를 넘을 수 있는 회차 {near}건 — 프롬프트 길이를 확인하세요")
    if capped:
        print(f"  ⚠️  출력이 num_predict({OPTIONS_V2['num_predict']}) 상한에 걸린 회차 {capped}건")
    print("채점: uv run python src/score_v2.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
