"""채택 구성 회귀 게이트 (v1.5) — 평가셋 aether_raid_v14 개발용 / 방법 M2 / 출력 형식 v2.

v1.4에서 채택한 구성(qwen2.5:7b + Critical 체크리스트 M2)의 고정 기준선과 후보 실행을 seed 3개로 비교해,
gate_criteria_v14.toml 의 합격 기준으로 "나빠지지 않았는가"를 판정한다. 실행은 uv run triage-gate --dataset v14.

사용법
------
    uv run triage-run --dataset v14 --method m2 --seed 1 --strict-env      # seed 11, 21 도 같은 방법으로
    uv run triage-gate --dataset v14 --candidate <seed1.json> --candidate <seed11.json> --candidate <seed21.json>

종료 코드
---------
    0  PASS (seed 3개 모두 통과)   1  FAIL   2  판정 불가 (비교 조건 불일치, seed 누락, 개발용 아님, 기준 파일 오류)

출력
----
    data/results/v14/gate_result_v14.json   기계 판독용 판정 결과
    report/regression_gate_v14.md           사람이 읽는 판정 근거 (seed별 기준 판정, 문항 단위 변화)

[설계 의도]
1. 채점·집계·판정은 v1.3 게이트(gate.py)와 v1.4 비교 도구(compare.py)의 함수를 그대로 쓴다. 판정 규칙을 따로 두면
   방법을 채택한 비교와 게이트의 판정이 어긋난다. 이 파일에는 seed 짝 맞추기, 비교 조건 확인, 출력만 둔다.
2. seed 3개(1·11·21)가 모두 통과해야 PASS다. seed 하나로는 효과와 우연을 구분할 수 없었다(docs/issue_log.md KL-002).
3. X-2·X-3은 0건이 아니라 "기준선보다 늘지 않을 것"으로 판정한다. 기준선(M2)도 개발용 63건에서 X-3이 0건이 아니라,
   0건을 요구하면 기준선 자신이 탈락한다. 0건 기준은 최종 측정과 v1.5 라우팅 목표에서 판정한다.
4. 평균 지연은 절대 상한(1건 10초)과 기준선 대비 증가율(20%)을 모두 본다. v1.4 방법 비교에서는 호출이 늘어나는
   방법을 비교해 증가율을 쓰지 않았지만, 게이트는 평소 변경을 판정하므로 의도하지 않은 지연 증가도 잡는다.
5. 비교 전에 비교해도 되는지 확인한다. 기준선과 후보가 모두 v1.4 평가셋 개발용이고, seed가 기준 파일과 같고,
   평가셋·문항·생성 옵션·반복 횟수·대상 모델 digest가 같아야 한다. 후보 3개끼리는 모든 실행 조건이 같아야 한다
   (seed마다 다른 구성이면 무엇을 판정했는지 알 수 없다). 하나라도 어긋나면 판정하지 않는다(종료 코드 2).
   프롬프트·방법·안전장치·재요청·폐기 확인은 기준선과 달라도 된다. 게이트가 판정하려는 변경이기 때문이며, 차이는 결과에 적는다.
6. 기준 파일에 모르는 섹션·키가 있거나 필요한 키가 없으면 판정하지 않는다(v1.1.1 ISSUE-003).
7. 실행 도중 모델이 다시 로드된 실행(워밍업을 뺀 응답의 로드 시간이 RELOAD_SEC 초과)은 측정 환경 오염으로 보고
   판정하지 않는다. 다시 로드되면 같은 seed라도 그 뒤 응답이 재현되지 않으므로(docs/issue_log.md OBS-005), FAIL로
   판정하면 변경의 효과와 환경 탓을 구분할 수 없다. 정상 응답의 로드 시간은 0.01초 미만이고, 다시 로드되면 수 초가
   걸린다(OBS-005 실측 8.2·16.4초). 이 확인은 품질 기준이 아니라 "비교해도 되는가"의 조건이라 기준 파일에 두지 않는다.
   실행 기록에는 각 문항의 첫 호출 로드 시간만 남으므로, 형식 재요청·체크리스트·폐기 확인 호출에서 다시 로드된 경우는
   이 확인으로 잡지 못한다.
"""

import json
import tomllib
from pathlib import Path

from triage_eval.common.paths import ROOT
from triage_eval.pipeline import compare as cmp
from triage_eval.pipeline import gate as g

CRITERIA = ROOT / "gate_criteria_v14.toml"
DATASET = ROOT / "data" / "eval_v14" / "aether_raid_v14.json"
RESULT_JSON = ROOT / "data" / "results" / "v14" / "gate_result_v14.json"
REPORT = ROOT / "report" / "regression_gate_v14.md"

KNOWN = {
    "meta": {"version", "dataset", "split", "seeds", "repeat", "target_model", "baseline"},
    "absolute": {"success_rate_min", "hallucination_max", "language_violation_max", "enum_violation_max",
                 "latency_max_sec"},
    "relative_to_baseline": {"x2_miss_increase_max", "x3_miss_increase_max"},
    "regression": {"x1_miss_increase_max", "over_escalation_increase_max", "format_drop_max_responses",
                   "latency_increase_max_pct", "field_drop_max_responses", "item_regression_max_responses"},
}
RELOAD_SEC = 1.0   # 설계 의도 7
SAME_DATA = (("dataset_sha256", "평가셋"), ("item_ids", "문항 구성"), ("options", "생성 옵션"), ("repeat_count", "반복 횟수"))
CHANGE_NOTES = (("prompt_version", "프롬프트 버전"), ("system_prompt_sha256", "프롬프트"), ("method", "방법"),
                ("method_assets_sha256", "방법 구성(예시·질문)"), ("guardrail_version", "후처리 안전장치"),
                ("retry_policy", "형식 재요청 정책"), ("discard_check_policy", "폐기 확인 정책"),
                ("critical_check_policy", "Critical 체크리스트 정책"), ("think", "생각 끄기 설정"))


def load_criteria(path: Path) -> dict:
    """설계 의도 6."""
    if not path.exists():
        raise g.GateError(f"기준 파일이 없습니다: {path}")
    c = tomllib.loads(path.read_text(encoding="utf-8"))
    problems = [f"모르는 섹션 [{s}]" for s in c if s not in KNOWN]
    problems += [f"[{s}] 모르는 키 {k!r}" for s, body in c.items() if s in KNOWN for k in body if k not in KNOWN[s]]
    problems += [f"[{s}] {k} 가 없습니다" for s, keys in KNOWN.items() for k in keys if k not in c.get(s, {})]
    reg = c.get("regression", {})
    problems += [f"[regression.field_drop_max_responses] 모르는 칸 {f!r}"
                 for f in reg.get("field_drop_max_responses", {}) if f not in g.FIELD_KEYS]
    problems += [f"[regression.item_regression_max_responses] 모르는 칸 {f!r}"
                 for f in reg.get("item_regression_max_responses", {}) if f not in g.JUDGED]
    meta = c.get("meta", {})
    if len(meta.get("baseline", [])) != len(meta.get("seeds", [])):
        problems.append("[meta] baseline 실행 기록 수가 seeds 수와 다릅니다")
    if problems:
        raise g.GateError("합격 기준 파일 오류 → " + "; ".join(problems))
    return c


def by_seed(logs: list[tuple[Path, dict]], name: str, crit: dict) -> dict[int, tuple[Path, dict]]:
    """설계 의도 5 — 실행 기록을 seed로 묶는다. 개발용이 아니거나 seed가 기준 파일과 다르면 GateError."""
    meta, out, problems, dirty = crit["meta"], {}, [], []
    for path, log in logs:
        md = log["metadata"]
        if md.get("dataset_version") != "v1.4":
            raise g.GateError(f"{name} {g.rel(path)} 이 v1.4 평가셋 실행이 아닙니다 ({md.get('dataset_version')})")
        if any(r.get("split") != meta["split"] for r in log["results"]):
            raise g.GateError(f"{name} {g.rel(path)} 에 개발용이 아닌 문항이 있습니다. 게이트는 개발용 실행만 판정합니다.")
        if meta["target_model"] not in md["models"]:
            problems.append(f"{name} {g.rel(path)} 에 {meta['target_model']} 결과가 없습니다")
        if md["run_config"].get("repeat_count") != meta["repeat"]:
            problems.append(f"{name} {g.rel(path)} 의 반복 횟수가 기준 파일({meta['repeat']})과 다릅니다")
        reloads = [r for r in log["results"] if r["model"] == meta["target_model"] and (r.get("load_duration_sec") or 0) > RELOAD_SEC]
        if reloads:   # 설계 의도 7
            where = ", ".join(f"{r['run_index']}회차 {r['item_id']}(로드 {r['load_duration_sec']}초)" for r in reloads)
            dirty.append(f"{g.rel(path)} [{where}]")
        seed = cmp.seed_of(log)
        if seed is None:
            problems.append(f"{name} {g.rel(path)} 이 seed 고정 모드가 아닙니다")
        elif seed in out:
            problems.append(f"{name} seed {seed} 실행이 중복되었습니다")
        else:
            out[seed] = (path, log)
    if dirty:
        raise g.GateError(f"측정 환경 오염 → {name} 실행 도중 모델이 다시 로드됨: " + "; ".join(dirty)
                          + ". 그 뒤 응답은 같은 seed로 재현되지 않습니다(OBS-005). 다른 Ollama 사용을 끄고 다시 실행하세요.")
    missing = [s for s in meta["seeds"] if s not in out]
    extra = [s for s in out if s not in meta["seeds"]]
    if missing or extra:
        problems.append(f"{name} seed 구성이 기준 파일과 다릅니다 (빠짐 {missing}, 남음 {extra})")
    if problems:
        raise g.GateError("비교 조건 불일치 → " + "; ".join(problems))
    return out


def check_comparable(base: dict[int, tuple[Path, dict]], cand: dict[int, tuple[Path, dict]], crit: dict) -> list[str]:
    """설계 의도 5 — 비교할 수 없으면 GateError. 기준선과 다른 실행 조건(판정하려는 변경)은 notes 로 돌려준다."""
    model, problems = crit["meta"]["target_model"], []
    c_cfgs = [log["metadata"]["run_config"] for _, log in cand.values()]
    first = c_cfgs[0]
    for key, label in SAME_DATA + CHANGE_NOTES:
        if any(c.get(key) != first.get(key) for c in c_cfgs[1:]):
            problems.append(f"후보 실행끼리 {label}이(가) 다릅니다")
    for seed, (_, b_log) in base.items():
        b, c = b_log["metadata"]["run_config"], cand[seed][1]["metadata"]["run_config"]
        for key, label in SAME_DATA:
            if b.get(key) != c.get(key):
                problems.append(f"seed {seed}: {label}이(가) 기준선과 다릅니다")
        if b["model_digests"].get(model) != c["model_digests"].get(model):
            problems.append(f"seed {seed}: {model} 모델 digest가 기준선과 다릅니다 (재pull 등)")
    if problems:
        raise g.GateError("비교 조건 불일치 → " + "; ".join(dict.fromkeys(problems)))
    b0 = next(iter(base.values()))[1]["metadata"]["run_config"]
    return [f"{label} 변경됨 (이 게이트가 판정하려는 변경)" for key, label in CHANGE_NOTES if b0.get(key) != first.get(key)]


def judge_criteria(crit: dict) -> dict:
    """compare.compare_seed 에 넘길 기준 (설계 의도 1·3·4). 지연 증가율은 [regression]에 있어 gate.judge 가 판정한다."""
    return {"absolute": crit["absolute"], "relative_to_baseline": crit["relative_to_baseline"],
            "regression": crit["regression"]}


def change_totals(per_seed: list[dict]) -> dict[str, dict[str, int]]:
    """seed 3개를 합친 칸별 문항 단위 변화 (새로 틀림·새로 맞힘)."""
    return {f: {k: sum(len(r["item_changes"][f][k]) for r in per_seed) for k in ("regressed", "fixed")}
            for f in g.FIELD_KEYS}


def render(crit, base, cand, notes, per_seed, totals, verdict) -> str:
    seeds = crit["meta"]["seeds"]
    L = ["# 채택 구성 회귀 게이트 판정 (v1.4 평가셋 · M2)", "",
         f"> 대상 `{crit['meta']['target_model']}` · 기준 파일 `gate_criteria_v14.toml` · "
         "`src/triage_eval/pipeline/gate_v14.py` 생성", "",
         f"## 판정: **{verdict}**", "",
         "| seed | 기준선 | 후보 | 결과 |", "| ---: | :--- | :--- | :---: |"]
    for s, r in zip(seeds, per_seed):
        L.append(f"| {s} | `{g.rel(base[s][0])}` | `{g.rel(cand[s][0])}` | {'PASS' if r['passed'] else 'FAIL'} |")
    L.append("")
    L += [f"- {n}" for n in notes] or ["- 기준선과 실행 조건이 같습니다 (기준선 재현 점검)"]
    L += ["", "## 칸별 문항 단위 변화 (seed 3개 합계)", "", "| 칸 | 새로 틀림 | 새로 맞힘 |", "| :--- | ---: | ---: |"]
    L += [f"| {f} | {t['regressed']} | {t['fixed']} |" for f, t in totals.items()]
    for s, r in zip(seeds, per_seed):
        L += ["", f"## seed {s}: {'PASS' if r['passed'] else 'FAIL'}", "",
              "| 기준 | 종류 | 기준선 | 후보 | 허용 | 결과 |", "| :--- | :--- | ---: | ---: | :--- | :---: |"]
        for c in r["checks"]:
            L.append(f"| {c['name']} | {c['kind']} | {'—' if c['baseline'] is None else c['baseline']} | "
                     f"{c['candidate']} | {c['limit']} | {'✅' if c['passed'] else '❌'} |")
        for f in g.JUDGED:
            reg = r["item_changes"][f]["regressed"]
            if reg:
                L += ["", f"**{f} — 기준선 정답 → 후보 오답**", ""]
                L += [f"- {e['item_id']} {e['run']}회차: {e['before']} → {e['after']}" for e in reg]
    return "\n".join(L) + "\n"


def run(cand_paths: list[Path], crit: dict, base_paths: list[Path] | None = None, write: bool = True) -> int:
    base_paths = base_paths or [ROOT / p for p in crit["meta"]["baseline"]]
    base = by_seed([(p, g.load_log(p)) for p in base_paths], "기준선", crit)
    cand = by_seed([(p, g.load_log(p)) for p in cand_paths], "후보", crit)
    notes = check_comparable(base, cand, crit)
    items = {i["id"]: i for i in json.loads(DATASET.read_text(encoding="utf-8"))["items"]}
    arm = f"m2/{crit['meta']['target_model']}"   # compare_seed 는 arm 에서 모델 이름만 쓴다
    per_seed = [cmp.compare_seed(base[s][1], cand[s][1], arm, arm, items, judge_criteria(crit)) for s in crit["meta"]["seeds"]]
    verdict = "PASS" if all(r["passed"] for r in per_seed) else "FAIL"
    totals = change_totals(per_seed)

    print(f"\n[{crit['meta']['target_model']}] {verdict}  (seed " +
          " / ".join(f"{s} {'PASS' if r['passed'] else 'FAIL'}" for s, r in zip(crit["meta"]["seeds"], per_seed)) + ")")
    for n in notes:
        print(f"  · {n}")
    for s, r in zip(crit["meta"]["seeds"], per_seed):
        for c in r["checks"]:
            if not c["passed"]:
                print(f"  ❌ seed {s}: {c['name']} {c['baseline']} → {c['candidate']} (허용 {c['limit']})")
    changed = {f: t for f, t in totals.items() if t["regressed"] or t["fixed"]}
    print("  문항 단위 변화(seed 합계): " + (", ".join(f"{f} 새로 틀림 {t['regressed']}·새로 맞힘 {t['fixed']}"
                                              for f, t in changed.items()) or "없음"))
    if write:
        RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
        RESULT_JSON.write_text(json.dumps({
            "verdict": verdict, "target_model": crit["meta"]["target_model"], "notes": notes,
            "baseline": [g.rel(base[s][0]) for s in crit["meta"]["seeds"]],
            "candidate": [g.rel(cand[s][0]) for s in crit["meta"]["seeds"]],
            "item_change_totals": totals, "per_seed": per_seed}, ensure_ascii=False, indent=2), encoding="utf-8")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(render(crit, base, cand, notes, per_seed, totals, verdict), encoding="utf-8")
        print(f"\n저장: {g.rel(RESULT_JSON)}, {g.rel(REPORT)}")
    return 0 if verdict == "PASS" else 1
