"""v1.4 모델 선택 판정 — 현재 선정 모델과 후보 모델을 같은 조건의 실행으로 비교해 교체 여부를 정한다.

사용법
------
    # 1) seed 3개로 실행 (모델마다 실행 전에 메모리에서 내린다 — run.py 설계 의도 9)
    uv run triage-run --seed 1  --strict-env --model qwen2.5:7b --model gemma4:12b
    uv run triage-run --seed 11 --strict-env --model qwen2.5:7b --model gemma4:12b
    uv run triage-run --seed 21 --strict-env --model qwen2.5:7b --model gemma4:12b
    # 2) 세 실행 기록으로 판정
    uv run triage-select --run <seed1.json> --run <seed11.json> --run <seed21.json>

종료 코드
---------
    0  후보로 교체   1  현재 모델 유지   2  판정 불가 (비교 조건 불일치, 평가용 실행, 기준 파일 오류, 파일 없음)

출력
----
    data/results/v14/selection_result_v14.json   기계 판독용 판정 결과
    report/model_selection_v14.md                사람이 읽는 판정 근거

[설계 의도]
1. 채점과 판정은 회귀 게이트(gate.py)의 함수를 그대로 쓴다. 절대 기준·회귀 기준 값도 gate_criteria_v13.toml 에서
   읽는다. 판정 규칙이나 허용폭이 두 곳에 있으면 한쪽만 고쳐졌을 때 게이트와 모델 선택이 어긋난다.
   모델 선택에만 필요한 값(지연 절대 기준, seed 수)만 model_selection_v14.toml 에 둔다.
2. 모델 말고는 모든 조건이 같아야 비교한다. 평가셋·생성 옵션·문항·반복 횟수에 더해 프롬프트·형식 재요청·
   폐기 확인·후처리 안전장치·생각 끄기 설정까지 세 실행이 모두 같아야 한다. 게이트는 프롬프트가 달라도 되지만
   (프롬프트 변경을 판정하는 도구이므로), 모델 비교에서 프롬프트까지 바뀌면 차이가 모델 때문인지 알 수 없다
   (프롬프트 엔지니어링 과정의 비교 쌍 분리, 머신러닝 과정의 공정한 비교 계약).
3. 지연은 증가율이 아니라 절대값으로 판정한다. 게이트의 "지연 증가 20% 이하"는 같은 모델에서 프롬프트를 고칠 때의
   기준이라, 크기가 다른 모델의 비교에는 맞지 않는다. 기준값(1건 평균 10초)은 사람의 BTS 작성 시간(평균 3~5분)과
   업데이트 직후 제보 집중 시 처리량(PC 1대 시간당 360건)으로 정했다. 증가율은 참고로 기록한다.
4. seed 하나의 결과로 정하지 않는다. 같은 seed끼리 짝지어 비교하고, 모든 seed에서 기준을 통과해야 교체 대상이 된다.
   seed 하나로는 효과와 샘플링 변동을 구분할 수 없다(docs/issue_log.md ISSUE-007, v2.4 기각 사례).
5. 나빠지지 않은 것만으로는 바꾸지 않는다. 모든 seed에서 통과한 후보 중, seed 합계로 X-1 누락이 줄었거나
   (같으면) 우선순위 정답이 늘어난 후보만 교체 대상이다. 개선이 없으면 현재 모델을 유지한다. 교체에는 지연·재검증
   비용이 들기 때문이다. 교체 대상이 여럿이면 X-1 누락 합계 → 우선순위 정답 합계 → 평균 지연 순으로 고른다.
   이 규칙은 측정 전에 정했다(2026-10-02).
6. 평가용(test) 문항이 섞인 실행은 판정을 거부한다. 모델 선택은 개발용으로 하고, 확정은 새 평가 문항으로 한다.
7. 판정(decide)은 집계값만 받는 순수 함수로 두어, 선택 규칙을 실행 기록 없이 테스트할 수 있게 한다.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path
from statistics import mean

from triage_eval.common.paths import ROOT
from triage_eval.pipeline import gate as g

SELECT_CRITERIA = ROOT / "model_selection_v14.toml"
RESULT_JSON = ROOT / "data" / "results" / "v14" / "selection_result_v14.json"
REPORT = ROOT / "report" / "model_selection_v14.md"
KNOWN = {"meta": {"version", "baseline_model", "seed_runs", "gate_criteria"}, "absolute": {"latency_max_sec"}}
SAME_CONFIG = (("dataset_sha256", "평가셋"), ("options", "생성 옵션"), ("item_ids", "문항 구성"),
               ("repeat_count", "반복 횟수"), ("prompt_version", "프롬프트 버전"),
               ("system_prompt_sha256", "프롬프트 지문"), ("guardrail_version", "후처리 안전장치"),
               ("retry_policy", "형식 재요청 정책"), ("discard_check_policy", "폐기 확인 정책"), ("think", "생각 끄기 설정"))


def load_select_criteria(path: Path) -> tuple[dict, dict]:
    """모델 선택 기준과, 거기서 가리키는 게이트 기준(설계 의도 1)을 함께 읽는다."""
    if not path.exists():
        raise g.GateError(f"기준 파일이 없습니다: {path}")
    c = tomllib.loads(path.read_text(encoding="utf-8"))
    problems = [f"모르는 섹션 [{s}]" for s in c if s not in KNOWN]
    problems += [f"[{s}] 모르는 키 {k!r}" for s, body in c.items() if s in KNOWN for k in body if k not in KNOWN[s]]
    for s, k in (("meta", "baseline_model"), ("meta", "seed_runs"), ("meta", "gate_criteria"), ("absolute", "latency_max_sec")):
        if k not in c.get(s, {}):
            problems.append(f"[{s}] {k} 가 없습니다")
    if problems:
        raise g.GateError("모델 선택 기준 파일 오류 → " + "; ".join(problems))
    gate_crit = g.load_criteria(ROOT / c["meta"]["gate_criteria"])
    gate_crit = {**gate_crit, "regression": {k: v for k, v in gate_crit.get("regression", {}).items()
                                             if k != "latency_increase_max_pct"}}  # 설계 의도 3
    return c, gate_crit


def check_runs(logs: list[dict], baseline: str, seed_runs: int) -> list[str]:
    """설계 의도 2·4·6 — 비교할 수 없으면 GateError. 비교할 후보 모델 목록을 돌려준다."""
    if len(logs) != seed_runs:
        raise g.GateError(f"seed {seed_runs}개의 실행 기록이 필요합니다 (받은 수 {len(logs)})")
    problems = []
    for n, log in enumerate(logs, start=1):
        if any(r.get("split") != "dev" for r in log["results"]):
            raise g.GateError(f"{n}번째 실행에 평가용(test) 문항이 있습니다. 모델 선택은 개발용 실행으로만 합니다.")
        if log["metadata"]["run_config"].get("seeds") is None:
            problems.append(f"{n}번째 실행이 seed 고정 모드가 아닙니다")
        if baseline not in log["metadata"]["models"]:
            problems.append(f"{n}번째 실행에 현재 모델({baseline})이 없습니다")
    first = logs[0]["metadata"]["run_config"]
    for n, log in enumerate(logs[1:], start=2):
        c = log["metadata"]["run_config"]
        for key, label in SAME_CONFIG:
            if c.get(key) != first.get(key):
                problems.append(f"{n}번째 실행의 {label}이(가) 1번째와 다릅니다")
    for key, label in SAME_CONFIG:
        if key not in first:
            problems.append(f"실행 기록에 {label} 기록이 없습니다 (v1.4 이전 실행)")
    seeds = [json.dumps(log["metadata"]["run_config"].get("seeds"), sort_keys=True) for log in logs]
    if len(set(seeds)) != len(seeds):
        problems.append("같은 seed의 실행이 중복되었습니다")
    models = [log["metadata"]["models"] for log in logs]
    if any(set(m) != set(models[0]) for m in models):
        problems.append("세 실행의 모델 구성이 다릅니다")
    candidates = [m for m in models[0] if m != baseline]
    if not candidates:
        problems.append("비교할 후보 모델이 없습니다")
    if problems:
        raise g.GateError("비교 조건 불일치 → " + "; ".join(problems))
    return candidates


def compare_seed(log: dict, baseline: str, candidate: str, items: dict, gate_crit: dict, latency_max: float) -> dict:
    """같은 실행(같은 seed) 안에서 현재 모델 vs 후보 모델."""
    b_rows, c_rows = g.score_log(log, baseline, items), g.score_log(log, candidate, items)
    bc, cc = g.counts(b_rows), g.counts(c_rows)
    changes = g.item_changes(b_rows, c_rows)
    checks = g.judge(bc, cc, changes, gate_crit)
    checks.append({"name": "평균 지연(초)", "kind": "절대", "baseline": bc["latency"], "candidate": cc["latency"],
                   "limit": f"≤ {latency_max}", "passed": cc["latency"] is not None and cc["latency"] <= latency_max})
    pct = round((cc["latency"] - bc["latency"]) / bc["latency"] * 100, 1) if bc["latency"] and cc["latency"] else None
    return {"seeds": log["metadata"]["run_config"]["seeds"], "passed": all(c["passed"] for c in checks),
            "checks": checks, "baseline": bc, "candidate": cc, "latency_change_pct": pct, "item_changes": changes}


def summarize(per_seed: list[dict]) -> dict:
    """seed 합계 — 선택 규칙(설계 의도 5)에 쓰는 값만 모은다."""
    return {
        "all_seeds_passed": all(s["passed"] for s in per_seed),
        "x1_base": sum(s["baseline"]["x1"] for s in per_seed), "x1_cand": sum(s["candidate"]["x1"] for s in per_seed),
        "pri_base": sum(s["baseline"]["fields_ok"]["우선순위"] for s in per_seed),
        "pri_cand": sum(s["candidate"]["fields_ok"]["우선순위"] for s in per_seed),
        "latency_cand": round(mean(s["candidate"]["latency"] for s in per_seed), 3),
    }


def improved(s: dict) -> bool:
    return s["x1_cand"] < s["x1_base"] or (s["x1_cand"] == s["x1_base"] and s["pri_cand"] > s["pri_base"])


def decide(summaries: dict[str, dict]) -> tuple[str | None, dict[str, str]]:
    """설계 의도 5·7 — (교체할 모델 또는 None, 후보별 사유)."""
    reasons, eligible = {}, []
    for model, s in summaries.items():
        if not s["all_seeds_passed"]:
            reasons[model] = "기준 미통과 (seed 중 하나 이상에서 절대·회귀 기준 FAIL)"
        elif not improved(s):
            reasons[model] = (f"개선 없음 (X-1 누락 {s['x1_base']}→{s['x1_cand']}, "
                              f"우선순위 정답 {s['pri_base']}→{s['pri_cand']})")
        else:
            reasons[model] = (f"교체 조건 충족 (X-1 누락 {s['x1_base']}→{s['x1_cand']}, "
                              f"우선순위 정답 {s['pri_base']}→{s['pri_cand']})")
            eligible.append(model)
    if not eligible:
        return None, reasons
    best = min(eligible, key=lambda m: (summaries[m]["x1_cand"], -summaries[m]["pri_cand"], summaries[m]["latency_cand"]))
    return best, reasons


def render(baseline, run_paths, results, summaries, chosen, reasons) -> str:
    L = ["# v1.4 모델 선택 판정", "",
         f"> 현재 모델 `{baseline}` · 실행 기록 " + ", ".join(f"`{g.rel(p)}`" for p in run_paths)
         + " · `src/triage_eval/pipeline/selection.py` 생성", "",
         f"## 결정: **{'`' + chosen + '`(으)로 교체' if chosen else '현재 모델 유지'}**", ""]
    for m, r in reasons.items():
        L.append(f"- `{m}`: {r}")
    for m, per_seed in results.items():
        s = summaries[m]
        L += ["", f"## `{m}`", "",
              f"seed 합계 — X-1 누락 {s['x1_base']} → {s['x1_cand']}, 우선순위 정답 {s['pri_base']} → {s['pri_cand']}, "
              f"후보 평균 지연 {s['latency_cand']}초", ""]
        for r in per_seed:
            seeds = ",".join(str(v) for v in r["seeds"].values())
            L += [f"### seed {seeds}: {'PASS' if r['passed'] else 'FAIL'} (지연 변화 {r['latency_change_pct']}%, 참고)", "",
                  "| 기준 | 종류 | 현재 모델 | 후보 | 허용 | 결과 |", "| :--- | :--- | ---: | ---: | :--- | :---: |"]
            for c in r["checks"]:
                L.append(f"| {c['name']} | {c['kind']} | {'—' if c['baseline'] is None else c['baseline']} | "
                         f"{c['candidate']} | {c['limit']} | {'✅' if c['passed'] else '❌'} |")
            L.append("")
    return "\n".join(L) + "\n"


def run(run_paths: list[Path], crit: dict, gate_crit: dict, write: bool = True) -> int:
    logs = [g.load_log(p) for p in run_paths]
    baseline = crit["meta"]["baseline_model"]
    candidates = check_runs(logs, baseline, crit["meta"]["seed_runs"])
    items = {i["id"]: i for i in json.loads(g.DATASET.read_text(encoding="utf-8"))["items"]}
    lat = crit["absolute"]["latency_max_sec"]
    results = {m: [compare_seed(log, baseline, m, items, gate_crit, lat) for log in logs] for m in candidates}
    summaries = {m: summarize(r) for m, r in results.items()}
    chosen, reasons = decide(summaries)
    for m, per_seed in results.items():
        print(f"\n[{m}] " + " / ".join(("PASS" if r["passed"] else "FAIL") for r in per_seed) + f" — {reasons[m]}")
        for r in per_seed:
            for c in r["checks"]:
                if not c["passed"]:
                    print(f"  ❌ seed {list(r['seeds'].values())[0]}: {c['name']} {c['baseline']} → {c['candidate']} (허용 {c['limit']})")
    print(f"\n결정: {chosen + '(으)로 교체' if chosen else '현재 모델(' + baseline + ') 유지'}")
    if write:
        RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
        RESULT_JSON.write_text(json.dumps({"baseline_model": baseline, "runs": [g.rel(p) for p in run_paths],
                                           "chosen": chosen, "reasons": reasons, "summaries": summaries,
                                           "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(render(baseline, run_paths, results, summaries, chosen, reasons), encoding="utf-8")
        print(f"저장: {g.rel(RESULT_JSON)}, {g.rel(REPORT)}")
    return 0 if chosen else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v1.4 모델 선택 판정")
    p.add_argument("--run", type=Path, action="append", required=True, help="seed별 실행 기록 (seed 수만큼 지정)")
    p.add_argument("--criteria", type=Path, default=SELECT_CRITERIA)
    p.add_argument("--no-write", action="store_true", help="결과 파일을 쓰지 않음")
    args = p.parse_args(argv)
    try:
        crit, gate_crit = load_select_criteria(args.criteria)
        return run(args.run, crit, gate_crit, write=not args.no_write)
    except g.GateError as e:
        print(f"판정 불가: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
