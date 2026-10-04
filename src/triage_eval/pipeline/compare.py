"""v1.4 방법·모델 비교 판정 — 사전 등록한 기준(method_selection_v14.toml)으로 채택 여부를 정한다.

계획: report/method_comparison_v14_plan.md

사용법
------
    # 실험 A — 모델 고정, 방법 비교 (seed 1·11·21 × 방법마다 1회씩 실행)
    uv run triage-run --dataset v14 --seed 1 --strict-env --method m0     # m1, m2 도 같은 seed로
    ...
    uv run triage-compare --label a --run <m0 seed1> --run <m0 seed11> ... --run <m2 seed21>

    # 실험 B — 방법 고정, 모델 비교 (실험 A에서 정해진 방법 X)
    uv run triage-run --dataset v14 --seed 1 --strict-env --method X --model qwen2.5:7b --model gemma4:12b
    ...
    uv run triage-compare --label b --baseline X/qwen2.5:7b --run <seed1> --run <seed11> --run <seed21>

    "비교 대상(arm)"은 방법/모델 한 쌍이다. 기준 arm 은 기본값이 기준 파일의 baseline_method/baseline_model 이고,
    실행 기록에 있는 나머지 arm 이 모두 후보가 된다.

종료 코드
---------
    0  후보 채택   1  기준 유지   2  판정 불가 (비교 조건 불일치, 개발용 아님, seed 누락, 기준 파일 오류)

출력
----
    data/results/v14/compare_<label>.json   기계 판독용 판정 결과
    report/method_comparison_v14_<label>.md 사람이 읽는 판정 근거

[설계 의도]
1. 채점·집계·판정 함수는 회귀 게이트(gate.py)와 모델 선택(selection.py)의 것을 그대로 쓴다. 이 파일에는
   v1.4 계획에서 새로 정한 것(기준선 대비 X-2·X-3, 기준 파일 읽기, arm 단위 묶기)만 둔다.
2. 절대·회귀 기준 값은 method_selection_v14.toml 한 곳에서 읽는다. 측정 전에 커밋한 파일이며 결과를 본 뒤 바꾸지 않는다.
3. 비교할 수 있는 실행인지 먼저 확인한다. 모든 실행이 v1.4 평가셋 개발용이고, 기준 파일의 seed가 빠짐없이 있고,
   비교 대상(방법 또는 모델) 말고 다른 조건(평가셋·생성 옵션·문항·반복·프롬프트·재요청·폐기 확인·안전장치·생각 끄기,
   같은 모델의 digest)이 같아야 한다. 하나라도 어긋나면 판정하지 않는다(종료 코드 2).
4. 최종 평가용(final) 문항이 하나라도 섞인 실행은 판정을 거부한다. 방법·모델 선택은 개발용으로만 한다.
5. 결정 규칙 4(M1·M2가 모두 채택 대상이면 M1+M2 추가 측정)는 도구가 대신 실행하지 않는다. 조건이 성립하면
   안내를 출력하고, M1+M2 실행 기록을 함께 넣어 다시 판정하게 한다.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

from triage_eval.common.paths import ROOT
from triage_eval.pipeline import gate as g
from triage_eval.pipeline import selection as sel

CRITERIA = ROOT / "method_selection_v14.toml"
DATASET = ROOT / "data" / "eval_v14" / "aether_raid_v14.json"
OUT_DIR = ROOT / "data" / "results" / "v14"
REPORT_DIR = ROOT / "report"
KNOWN = {
    "meta": {"version", "dataset", "split", "seeds", "repeat", "baseline_method", "baseline_model",
             "candidate_methods", "conditional_methods"},
    "absolute": {"success_rate_min", "hallucination_max", "language_violation_max", "enum_violation_max",
                 "latency_max_sec"},
    "relative_to_baseline": {"x2_miss_increase_max", "x3_miss_increase_max"},
    "regression": {"x1_miss_increase_max", "over_escalation_increase_max", "format_drop_max_responses",
                   "field_drop_max_responses", "item_regression_max_responses"},
}
SAME_CONFIG = (("dataset_sha256", "평가셋"), ("options", "생성 옵션"), ("item_ids", "문항 구성"),
               ("repeat_count", "반복 횟수"), ("prompt_version", "프롬프트 버전"),
               ("system_prompt_sha256", "프롬프트 지문"), ("guardrail_version", "후처리 안전장치"),
               ("retry_policy", "형식 재요청 정책"), ("discard_check_policy", "폐기 확인 정책"), ("think", "생각 끄기 설정"))


def load_criteria(path: Path) -> dict:
    if not path.exists():
        raise g.GateError(f"기준 파일이 없습니다: {path}")
    c = tomllib.loads(path.read_text(encoding="utf-8"))
    problems = [f"모르는 섹션 [{s}]" for s in c if s not in KNOWN]
    problems += [f"[{s}] 모르는 키 {k!r}" for s, body in c.items() if s in KNOWN for k in body if k not in KNOWN[s]]
    for s, keys in KNOWN.items():
        if s == "regression":
            continue
        problems += [f"[{s}] {k} 가 없습니다" for k in keys if k not in c.get(s, {})]
    if problems:
        raise g.GateError("방법 선택 기준 파일 오류 → " + "; ".join(problems))
    return c


def arms_of(log: dict) -> list[str]:
    method = log["metadata"]["run_config"].get("method", "m0")
    return [f"{method}/{m}" for m in log["metadata"]["models"]]


def seed_of(log: dict) -> int | None:
    seeds = log["metadata"]["run_config"].get("seeds")
    return seeds.get("1") if seeds else None


def check_runs(logs: list[dict], crit: dict, baseline: str) -> dict[str, dict[int, dict]]:
    """설계 의도 3·4 — {arm: {seed: 실행 기록}}. 비교할 수 없으면 GateError."""
    meta, problems = crit["meta"], []
    for n, log in enumerate(logs, start=1):
        md = log["metadata"]
        if md.get("dataset_version") != "v1.4":
            raise g.GateError(f"{n}번째 실행이 v1.4 평가셋 실행이 아닙니다 ({md.get('dataset_version')})")
        if any(r.get("split") != meta["split"] for r in log["results"]):
            raise g.GateError(f"{n}번째 실행에 개발용이 아닌 문항이 있습니다. 비교는 개발용 실행으로만 합니다.")
        if seed_of(log) is None:
            problems.append(f"{n}번째 실행이 seed 고정 모드가 아닙니다")
        if md["run_config"].get("repeat_count") != meta["repeat"]:
            problems.append(f"{n}번째 실행의 반복 횟수가 기준 파일({meta['repeat']})과 다릅니다")
    first = logs[0]["metadata"]["run_config"]
    for n, log in enumerate(logs[1:], start=2):
        c = log["metadata"]["run_config"]
        problems += [f"{n}번째 실행의 {label}이(가) 1번째와 다릅니다" for key, label in SAME_CONFIG if c.get(key) != first.get(key)]
    digests: dict[str, str] = {}
    by_arm: dict[str, dict[int, dict]] = {}
    assets: dict[str, str | None] = {}
    for n, log in enumerate(logs, start=1):
        c = log["metadata"]["run_config"]
        for model in log["metadata"]["models"]:
            d = c["model_digests"].get(model)
            if digests.setdefault(model, d) != d:
                problems.append(f"{model} 모델 digest가 실행마다 다릅니다 (재pull 등)")
        method = c.get("method", "m0")
        if assets.setdefault(method, c.get("method_assets_sha256")) != c.get("method_assets_sha256"):
            problems.append(f"방법 {method}의 구성(예시·질문)이 실행마다 다릅니다")
        for arm in arms_of(log):
            seed = seed_of(log)
            if seed in by_arm.setdefault(arm, {}):
                problems.append(f"{arm} seed {seed} 실행이 중복되었습니다")
            by_arm[arm][seed] = log
    if baseline not in by_arm:
        problems.append(f"기준 {baseline} 의 실행이 없습니다")
    for arm, runs in by_arm.items():
        missing = [s for s in meta["seeds"] if s not in runs]
        extra = [s for s in runs if s not in meta["seeds"]]
        if missing or extra:
            problems.append(f"{arm} 의 seed 구성이 기준 파일과 다릅니다 (빠짐 {missing}, 남음 {extra})")
    if len(by_arm) < 2:
        problems.append("비교할 후보가 없습니다")
    if problems:
        raise g.GateError("비교 조건 불일치 → " + "; ".join(problems))
    return by_arm


def gate_criteria(crit: dict) -> dict:
    """gate.judge 에 넘길 기준 — X-2·X-3 절대 기준과 지연 증가율은 넣지 않는다(설계 의도 1, 계획 §3)."""
    a = {k: v for k, v in crit["absolute"].items() if k != "latency_max_sec"}
    return {"absolute": a, "regression": crit.get("regression", {})}


def compare_seed(base_log: dict, cand_log: dict, base_arm: str, cand_arm: str, items: dict, crit: dict) -> dict:
    b_model, c_model = base_arm.split("/", 1)[1], cand_arm.split("/", 1)[1]
    b_rows, c_rows = g.score_log(base_log, b_model, items), g.score_log(cand_log, c_model, items)
    bc, cc = g.counts(b_rows), g.counts(c_rows)
    changes = g.item_changes(b_rows, c_rows)
    checks = g.judge(bc, cc, changes, gate_criteria(crit))
    rel = crit["relative_to_baseline"]
    for key, label, field in (("x2_miss_increase_max", "X-2 결함 폐기", "x2"), ("x3_miss_increase_max", "X-3 경계 건 확정 처리", "x3")):
        lim = rel[key]
        checks.append({"name": label, "kind": "기준선 대비", "baseline": bc[field], "candidate": cc[field],
                       "limit": f"증가 ≤ {lim}", "passed": cc[field] - bc[field] <= lim})
    lat = crit["absolute"]["latency_max_sec"]
    checks.append({"name": "평균 지연(초)", "kind": "절대", "baseline": bc["latency"], "candidate": cc["latency"],
                   "limit": f"≤ {lat}", "passed": cc["latency"] is not None and cc["latency"] <= lat})
    return {"seeds": cand_log["metadata"]["run_config"]["seeds"], "passed": all(c["passed"] for c in checks),
            "checks": checks, "baseline": bc, "candidate": cc, "item_changes": changes}


def conditional_note(crit: dict, chosen_pool: dict[str, dict], arms: list[str]) -> str | None:
    """설계 의도 5 — M1·M2가 모두 채택 대상인데 M1+M2 실행이 없으면 안내한다."""
    eligible_methods = {a.split("/", 1)[0] for a, s in chosen_pool.items() if s["all_seeds_passed"] and sel.improved(s)}
    if {"m1", "m2"} <= eligible_methods and not any(a.startswith("m1m2/") for a in arms):
        return "M1·M2가 모두 채택 대상입니다. 결정 규칙 4에 따라 M1+M2(--method m1m2)를 같은 seed로 실행해 함께 판정하세요."
    return None


def render(label, baseline, run_paths, results, summaries, chosen, reasons, note) -> str:
    L = [f"# v1.4 비교 판정 ({label})", "",
         f"> 기준 `{baseline}` · 기준 파일 `method_selection_v14.toml` · `src/triage_eval/pipeline/compare.py` 생성", "",
         f"## 결정: **{'`' + chosen + '` 채택' if chosen else '기준 유지'}**", ""]
    L += [f"- `{a}`: {r}" for a, r in reasons.items()]
    if note:
        L += ["", f"> {note}"]
    for arm, per_seed in results.items():
        s = summaries[arm]
        L += ["", f"## `{arm}`", "",
              f"seed 합계 — X-1 누락 {s['x1_base']} → {s['x1_cand']}, 우선순위 정답 {s['pri_base']} → {s['pri_cand']}, "
              f"후보 평균 지연 {s['latency_cand']}초", ""]
        for r in per_seed:
            L += [f"### seed {r['seeds']['1']}: {'PASS' if r['passed'] else 'FAIL'}", "",
                  "| 기준 | 종류 | 기준 | 후보 | 허용 | 결과 |", "| :--- | :--- | ---: | ---: | :--- | :---: |"]
            for c in r["checks"]:
                L.append(f"| {c['name']} | {c['kind']} | {'—' if c['baseline'] is None else c['baseline']} | "
                         f"{c['candidate']} | {c['limit']} | {'✅' if c['passed'] else '❌'} |")
            L.append("")
    L += ["", "실행 기록: " + ", ".join(f"`{g.rel(p)}`" for p in run_paths)]
    return "\n".join(L) + "\n"


def run(run_paths: list[Path], crit: dict, label: str, baseline: str | None = None, write: bool = True) -> int:
    baseline = baseline or f"{crit['meta']['baseline_method']}/{crit['meta']['baseline_model']}"
    logs = [g.load_log(p) for p in run_paths]
    by_arm = check_runs(logs, crit, baseline)
    items = {i["id"]: i for i in json.loads(DATASET.read_text(encoding="utf-8"))["items"]}
    seeds = crit["meta"]["seeds"]
    results = {arm: [compare_seed(by_arm[baseline][s], runs[s], baseline, arm, items, crit) for s in seeds]
               for arm, runs in by_arm.items() if arm != baseline}
    summaries = {arm: sel.summarize(r) for arm, r in results.items()}
    chosen, reasons = sel.decide(summaries)
    note = conditional_note(crit, summaries, list(by_arm))
    for arm, per_seed in results.items():
        print(f"\n[{arm}] " + " / ".join(("PASS" if r["passed"] else "FAIL") for r in per_seed) + f" — {reasons[arm]}")
        for r in per_seed:
            for c in r["checks"]:
                if not c["passed"]:
                    print(f"  ❌ seed {r['seeds']['1']}: {c['name']} {c['baseline']} → {c['candidate']} (허용 {c['limit']})")
    print(f"\n결정: {chosen + ' 채택' if chosen else '기준(' + baseline + ') 유지'}")
    if note:
        print(f"안내: {note}")
    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"compare_{label}.json"
        out.write_text(json.dumps({"label": label, "baseline": baseline, "runs": [g.rel(p) for p in run_paths],
                                   "chosen": chosen, "reasons": reasons, "note": note, "summaries": summaries,
                                   "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        report = REPORT_DIR / f"method_comparison_v14_{label}.md"
        report.write_text(render(label, baseline, run_paths, results, summaries, chosen, reasons, note), encoding="utf-8")
        print(f"저장: {g.rel(out)}, {g.rel(report)}")
    return 0 if chosen else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v1.4 방법·모델 비교 판정")
    p.add_argument("--run", type=Path, action="append", required=True, help="실행 기록 (arm × seed 수만큼)")
    p.add_argument("--label", choices=["a", "b"], required=True, help="a: 방법 비교, b: 모델 비교")
    p.add_argument("--baseline", default=None, help="기준 arm '방법/모델' (기본: 기준 파일 값)")
    p.add_argument("--criteria", type=Path, default=CRITERIA)
    p.add_argument("--no-write", action="store_true", help="결과 파일을 쓰지 않음")
    args = p.parse_args(argv)
    try:
        return run(args.run, load_criteria(args.criteria), args.label, args.baseline, write=not args.no_write)
    except g.GateError as e:
        print(f"판정 불가: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
