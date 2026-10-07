"""v1.3 회귀 게이트 — 평가셋 aether_raid_v13 / 출력 형식 v2.

기준선 실행과 후보 실행을 같은 채점기(score.score_one)로 다시 채점해 비교하고,
gate_criteria_v13.toml 의 합격 기준으로 판정한다.

사용법
------
    uv run triage-gate                                   # 고정 기준선 vs 가장 최근 개발용 실행
    uv run triage-gate --candidate <실행 기록.json>
    uv run triage-gate --model llama3.1:8b              # 대조군 확인용
    uv run triage-gate --dataset v14 --candidate <seed1> --candidate <seed11> --candidate <seed21>
                                                         # (v1.5) 채택 구성 게이트 → gate_v14.py

종료 코드
---------
    0  PASS   1  FAIL   2  판정 불가 (비교 조건 불일치, 평가용 실행, 기준 파일 오류, 파일 없음)

출력
----
    data/results/v13/gate_result_v13.json   기계 판독용 판정 결과
    report/regression_gate_v13.md           사람이 읽는 판정 근거 (문항 단위 변화 포함)

[설계 의도]
1. 채점은 score.score_one 을 그대로 쓴다. 게이트가 채점 규칙을 따로 가지면 채점 결과와 판정이 어긋난다.
   실행 기록(원본 응답)만 저장하고 채점 결과 파일은 읽지 않으므로, 채점기를 고치면 두 실행 모두 같은 규칙으로 다시 채점된다.
2. 비교 전에 "비교해도 되는가"를 확인한다. 평가셋·생성 옵션·seed·모델 digest 중 하나라도 다르면
   차이가 프롬프트 탓인지 조건 탓인지 구분할 수 없으므로 판정하지 않는다(종료 코드 2).
   프롬프트 지문은 달라도 된다. 이 게이트의 목적이 프롬프트 변경의 효과를 판정하는 것이기 때문이다.
3. 평가용(test) 문항이 섞인 실행은 판정을 거부한다. 프롬프트 개선 과정에서 평가용 점수를 보지 않기 위해서다.
4. 허용폭을 응답 수(정수)로 비교한다. 퍼센트로 바꿔 비교하면 부동소수점 오차로 경계값에서 판정이 뒤집힐 수 있다
   (v1.1.1 ISSUE-002와 같은 종류의 문제).
5. 문항 단위 회귀(기준선 정답 → 후보 오답)를 칸마다 센다. 합격 기준에 넣지 않은 칸도 목록으로 남겨,
   정답률이 유지된 채 문항이 뒤바뀌는 변화를 사람이 볼 수 있게 한다.
6. 기준 파일에 모르는 섹션·키가 있으면 판정하지 않는다. 오타로 기준이 조용히 꺼진 채 PASS가 나는 것을 막는다(v1.1.1 ISSUE-003).
7. (v1.5) --dataset v14 는 채택 구성 게이트(gate_v14.py)로 넘긴다. 기본값 v13은 이전과 똑같이 동작한다.
"""

import argparse
import json
import sys
import tomllib
from pathlib import Path
from statistics import mean

from triage_eval.common.paths import ROOT
from triage_eval.pipeline.score import JUDGED, score_one

CRITERIA = ROOT / "gate_criteria_v13.toml"
DATASET = ROOT / "data" / "eval_v13" / "aether_raid_v13.json"
HISTORY = ROOT / "data" / "results" / "v13" / "history"
RESULT_JSON = ROOT / "data" / "results" / "v13" / "gate_result_v13.json"
REPORT = ROOT / "report" / "regression_gate_v13.md"

FIELD_KEYS = JUDGED + ["6칸 정답"]
KNOWN = {
    "meta": {"version", "target_models", "baseline"},
    "absolute": {"success_rate_min", "hallucination_max", "x2_miss_max", "x3_miss_max", "language_violation_max",
                 "enum_violation_max"},
    "regression": {"x1_miss_increase_max", "over_escalation_increase_max", "format_drop_max_responses",
                   "latency_increase_max_pct", "field_drop_max_responses", "item_regression_max_responses"},
}


class GateError(Exception):
    """판정 자체가 성립하지 않음 → 종료 코드 2."""


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_criteria(path: Path) -> dict:
    if not path.exists():
        raise GateError(f"기준 파일이 없습니다: {path}")
    c = tomllib.loads(path.read_text(encoding="utf-8"))
    problems = []
    for section, body in c.items():
        if section not in KNOWN:
            problems.append(f"모르는 섹션 [{section}]")
            continue
        for key in body:
            if key not in KNOWN[section]:
                problems.append(f"[{section}] 모르는 키 {key!r}")
    reg = c.get("regression", {})
    for f in reg.get("field_drop_max_responses", {}):
        if f not in FIELD_KEYS:
            problems.append(f"[regression.field_drop_max_responses] 모르는 칸 {f!r}")
    for f in reg.get("item_regression_max_responses", {}):
        if f not in JUDGED:
            problems.append(f"[regression.item_regression_max_responses] 모르는 칸 {f!r}")
    if problems:
        raise GateError("합격 기준 파일 오류 → " + "; ".join(problems))
    return c


def load_log(path: Path) -> dict:
    if not path.exists():
        raise GateError(f"실행 기록이 없습니다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def latest_candidate(baseline: Path) -> Path:
    logs = [p for p in sorted(HISTORY.glob("v13_dev_*.json")) if p.resolve() != baseline.resolve()]
    if not logs:
        raise GateError("비교할 후보 실행이 없습니다. uv run triage-run 으로 개발용 실행을 먼저 하세요.")
    return logs[-1]


def check_comparable(base: dict, cand: dict, models: list[str]) -> list[str]:
    """설계 의도 2·3 — 비교할 수 없으면 GateError, 알려 둘 차이는 notes 로 돌려준다."""
    for name, log in (("기준선", base), ("후보", cand)):
        if any(r.get("split") != "dev" for r in log["results"]):
            raise GateError(f"{name} 실행에 평가용(test) 문항이 있습니다. 게이트는 개발용 실행만 판정합니다.")
    b, c = base["metadata"]["run_config"], cand["metadata"]["run_config"]
    problems = []
    for key, label in (("dataset_sha256", "평가셋"), ("options", "생성 옵션"), ("item_ids", "문항 구성"),
                       ("repeat_count", "반복 횟수"), ("seeds", "seed")):
        if b.get(key) != c.get(key):
            problems.append(f"{label}이(가) 다릅니다")
    if b.get("seeds") is None:
        problems.append("seed 고정 모드(--seed)가 아닌 실행은 응답이 재현되지 않아 판정할 수 없습니다")
    for m in models:
        if m not in base["metadata"]["models"] or m not in cand["metadata"]["models"]:
            problems.append(f"{m} 실행 결과가 한쪽에 없습니다")
        elif b["model_digests"].get(m) != c["model_digests"].get(m):
            problems.append(f"{m} 모델 digest가 다릅니다 (재pull 등)")
    if problems:
        raise GateError("비교 조건 불일치 → " + "; ".join(problems))
    notes = []
    if b.get("system_prompt_sha256") != c.get("system_prompt_sha256"):
        notes.append("프롬프트 변경됨 (이 게이트가 판정하려는 변경)")
    if b.get("guardrail_version") != c.get("guardrail_version"):
        notes.append(f"후처리 안전장치 변경됨 ({b.get('guardrail_version') or '없음'} → {c.get('guardrail_version') or '없음'})")
    if b.get("retry_policy") != c.get("retry_policy"):
        notes.append("형식 재요청 정책 변경됨 (" + ("없음" if not b.get("retry_policy") else "있음") + " → "
                     + ("없음" if not c.get("retry_policy") else "있음") + ")")
    if b.get("discard_check_policy") != c.get("discard_check_policy"):
        notes.append("폐기 확인 정책 변경됨 (" + ("없음" if not b.get("discard_check_policy") else "있음") + " → "
                     + ("없음" if not c.get("discard_check_policy") else "있음") + ")")
    return notes


def score_log(log: dict, model: str, items: dict) -> dict:
    """(문항, 회차) → 채점 행."""
    return {(r["item_id"], r["run_index"]): score_one(r, items[r["item_id"]])
            for r in log["results"] if r["model"] == model}


def ok(row: dict, field: str) -> bool:
    return row["all_fields_ok"] if field == "6칸 정답" else row["fields"][field]["ok"]


def counts(rows: dict) -> dict:
    vals = list(rows.values())
    lat = [r["elapsed_sec"] for r in vals if r["elapsed_sec"] is not None]
    return {
        "n": len(vals),
        "success": sum(r["success"] for r in vals),
        "strict": sum(r["format"]["strict_pass"] for r in vals),
        "parsable": sum(r["format"]["parsable_pass"] for r in vals),
        "fields_ok": {f: sum(ok(r, f) for r in vals) for f in FIELD_KEYS},
        "x1": sum("X-1" in r["risk_miss"] for r in vals),
        "x2": sum("X-2" in r["risk_miss"] for r in vals),
        "x3": sum("X-3" in r["risk_miss"] for r in vals),
        "over": sum(r["over_escalation"] for r in vals),
        "halluc": sum(r["hallucinated"] for r in vals),
        "lang": sum(not r["format"]["rules"]["R7_output_language"] for r in vals),
        "enum": sum(not r["format"]["rules"]["R6_enum_valid"] for r in vals),
        "latency": round(mean(lat), 3) if lat else None,
    }


def item_changes(base_rows: dict, cand_rows: dict) -> dict:
    """칸마다 기준선 정답→후보 오답(regressed), 오답→정답(fixed) 응답 목록."""
    out = {}
    for f in FIELD_KEYS:
        reg, fix = [], []
        for key in sorted(base_rows):
            if key not in cand_rows:
                continue
            b, c = ok(base_rows[key], f), ok(cand_rows[key], f)
            entry = {"item_id": key[0], "run": key[1]}
            if f != "6칸 정답":
                entry.update(before=base_rows[key]["fields"][f]["predicted"], after=cand_rows[key]["fields"][f]["predicted"])
            if b and not c:
                reg.append(entry)
            elif c and not b:
                fix.append(entry)
        out[f] = {"regressed": reg, "fixed": fix}
    return out


def judge(bc: dict, cc: dict, changes: dict, crit: dict) -> list[dict]:
    a, r = crit.get("absolute", {}), crit.get("regression", {})
    checks = []

    def add(name, kind, base_v, cand_v, limit, passed):
        checks.append({"name": name, "kind": kind, "baseline": base_v, "candidate": cand_v,
                       "limit": limit, "passed": bool(passed)})

    if "success_rate_min" in a:
        rate = round(cc["success"] / cc["n"] * 100, 2) if cc["n"] else 0.0
        add("호출 성공률(%)", "절대", None, rate, f"≥ {a['success_rate_min']}", rate >= a["success_rate_min"])
    for key, label, field in (("hallucination_max", "날조 응답", "halluc"), ("x2_miss_max", "X-2 결함 폐기", "x2"),
                              ("x3_miss_max", "X-3 경계 건 확정 처리", "x3"),
                              ("language_violation_max", "출력 언어 위반(R7)", "lang"),
                              ("enum_violation_max", "허용 값 위반(R6)", "enum")):
        if key in a:
            add(label, "절대", bc[field], cc[field], f"≤ {a[key]}", cc[field] <= a[key])
    if "x1_miss_increase_max" in r:
        lim = r["x1_miss_increase_max"]
        add("X-1 Critical 미상신", "회귀", bc["x1"], cc["x1"], f"증가 ≤ {lim}", cc["x1"] - bc["x1"] <= lim)
    if "over_escalation_increase_max" in r:
        lim = r["over_escalation_increase_max"]
        add("과잉 상신", "회귀", bc["over"], cc["over"], f"증가 ≤ {lim}", cc["over"] - bc["over"] <= lim)
    if "format_drop_max_responses" in r:
        lim = r["format_drop_max_responses"]
        for key, label in (("strict", "형식 STRICT(응답 수)"), ("parsable", "형식 PARSABLE(응답 수)")):
            add(label, "회귀", bc[key], cc[key], f"하락 ≤ {lim}", bc[key] - cc[key] <= lim)
    if "latency_increase_max_pct" in r and bc["latency"] and cc["latency"]:
        lim = r["latency_increase_max_pct"]
        pct = round((cc["latency"] - bc["latency"]) / bc["latency"] * 100, 2)
        add("평균 지연(초)", "회귀", bc["latency"], cc["latency"], f"증가 ≤ {lim}% (실제 {pct:+}%)", pct <= lim)
    for f, lim in r.get("field_drop_max_responses", {}).items():
        b, c = bc["fields_ok"][f], cc["fields_ok"][f]
        label = "6칸 모두 정답(응답 수)" if f == "6칸 정답" else f"{f} 정답(응답 수)"
        add(label, "회귀", b, c, f"하락 ≤ {lim}", b - c <= lim)
    for f, lim in r.get("item_regression_max_responses", {}).items():
        n = len(changes[f]["regressed"])
        add(f"{f} 문항 단위 회귀(응답 수)", "회귀", 0, n, f"≤ {lim}", n <= lim)
    return checks


def render(model, base_path, cand_path, notes, bc, cc, checks, changes, verdict) -> str:
    L = ["# v1.3 회귀 게이트 판정", "",
         f"> 기준선 `{rel(base_path)}` · 후보 `{rel(cand_path)}` · 대상 `{model}` · `src/triage_eval/pipeline/gate.py` 생성", "",
         f"## 판정: **{verdict}**", ""]
    for n in notes:
        L.append(f"- {n}")
    L += ["", "| 기준 | 종류 | 기준선 | 후보 | 허용 | 결과 |", "| :--- | :--- | ---: | ---: | :--- | :---: |"]
    for c in checks:
        L.append(f"| {c['name']} | {c['kind']} | {'—' if c['baseline'] is None else c['baseline']} | {c['candidate']} "
                 f"| {c['limit']} | {'✅' if c['passed'] else '❌'} |")
    L += ["", f"응답 수 {cc['n']} (응답 1개 = {round(100 / cc['n'], 2) if cc['n'] else 0}%p)", "",
          "## 칸별 문항 단위 변화", "", "| 칸 | 새로 틀림 | 새로 맞힘 |", "| :--- | ---: | ---: |"]
    for f in FIELD_KEYS:
        L.append(f"| {f} | {len(changes[f]['regressed'])} | {len(changes[f]['fixed'])} |")
    L.append("")
    for f in JUDGED:
        reg = changes[f]["regressed"]
        if reg:
            L += [f"**{f} — 기준선 정답 → 후보 오답**", ""]
            L += [f"- {e['item_id']} {e['run']}회차: {e['before']} → {e['after']}" for e in reg]
            L.append("")
    return "\n".join(L) + "\n"


def run(base_path: Path, cand_path: Path, models: list[str], crit: dict, write: bool = True) -> int:
    base, cand = load_log(base_path), load_log(cand_path)
    notes = check_comparable(base, cand, models)
    items = {i["id"]: i for i in json.loads(DATASET.read_text(encoding="utf-8"))["items"]}
    results, all_pass = {}, True
    for model in models:
        b_rows, c_rows = score_log(base, model, items), score_log(cand, model, items)
        bc, cc = counts(b_rows), counts(c_rows)
        changes = item_changes(b_rows, c_rows)
        checks = judge(bc, cc, changes, crit)
        verdict = "PASS" if all(c["passed"] for c in checks) else "FAIL"
        all_pass &= verdict == "PASS"
        results[model] = {"verdict": verdict, "checks": checks, "baseline": bc, "candidate": cc, "item_changes": changes}
        print(f"\n[{model}] {verdict}" + (f"  ({'; '.join(notes)})" if notes else ""))
        for c in checks:
            mark = "✅" if c["passed"] else "❌"
            print(f"  {mark} {c['name']}: 기준선 {c['baseline']} → 후보 {c['candidate']} (허용 {c['limit']})")
        if write:
            REPORT.parent.mkdir(parents=True, exist_ok=True)
            REPORT.write_text(render(model, base_path, cand_path, notes, bc, cc, checks, changes, verdict), encoding="utf-8")
    if write:
        RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
        RESULT_JSON.write_text(json.dumps({"baseline": rel(base_path), "candidate": rel(cand_path), "notes": notes,
                                           "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {rel(RESULT_JSON)}, {rel(REPORT)}")
    return 0 if all_pass else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="회귀 게이트 (v13: v1.3 평가셋 · v14: 채택 구성)")
    p.add_argument("--dataset", choices=["v13", "v14"], default="v13", help="평가셋 (기본: v13, 설계 의도 7)")
    p.add_argument("--baseline", type=Path, action="append", help="기준선 (v13: 1개, v14: seed 수만큼. 기본: 기준 파일 값)")
    p.add_argument("--candidate", type=Path, action="append", help="후보 (v13: 1개, 기본 가장 최근 실행 · v14: seed 수만큼)")
    p.add_argument("--model", action="append", help="대상 모델 (v13 전용, 기본: 기준 파일의 target_models)")
    p.add_argument("--criteria", type=Path, default=None)
    args = p.parse_args(argv)
    if args.dataset == "v14":
        from triage_eval.pipeline import gate_v14
        try:
            if not args.candidate:
                raise GateError("--candidate 로 seed마다 후보 실행 기록을 지정하세요 (seed 1·11·21)")
            crit = gate_v14.load_criteria(args.criteria or gate_v14.CRITERIA)
            return gate_v14.run(args.candidate, crit, args.baseline)
        except GateError as e:
            print(f"판정 불가: {e}")
            return 2
    try:
        if len(args.baseline or []) > 1 or len(args.candidate or []) > 1:
            raise GateError("v1.3 게이트는 기준선·후보를 1개씩만 받습니다")
        crit = load_criteria(args.criteria or CRITERIA)
        base_path = args.baseline[0] if args.baseline else ROOT / crit["meta"]["baseline"]
        cand_path = args.candidate[0] if args.candidate else latest_candidate(base_path)
        return run(base_path, cand_path, args.model or crit["meta"]["target_models"], crit)
    except GateError as e:
        print(f"판정 불가: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
