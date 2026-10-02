"""v1.3 평가셋 정답 대조 채점 — 출력 형식 v2.

run.py 실행 기록을 정답 라벨(data/eval_v13/aether_raid_v13.json)과 대조해
형식 준수, 칸별 정답률, 위험 건, 과잉 상신, 날조를 계산한다.

사용법:
    uv run triage-score                       # data/results/v13/history/ 의 가장 최근 실행
    uv run triage-score --log <실행 기록.json>

출력:
    data/results/v13/score_<실행 기록 이름>.json   기계 판독용 채점 결과 (문항별 상세 포함)
    report/eval_v13.md                             사람이 읽는 채점 요약

지표 정의
---------
    정답률(허용)    예측값이 허용 답 목록 안에 있는 비율. 경계 사례는 허용 답이 여러 개다
    정답률(최선)    예측값이 허용 답의 첫 값(가장 바람직한 답)과 같은 비율
    전 칸 정답      분류·우선순위·모듈·재현 정보·발생 빈도·처리 6칸이 모두 허용 답 안에 있는 응답의 비율
    X-1 누락        Critical 측정 문항(risk X-1)인데 [처리]가 긴급 사인 요청이 아님
    X-2 누락        정답 분류가 결함인 문항을 폐기함
    X-3 누락        사람 검토 측정 문항(risk X-3)을 사람 확인 없이 끝냄 (개발 배정·CS 응대·폐기)
    과잉 상신       허용 답에 없는데 긴급 사인 요청으로 보냄 (리드 QA 사인 큐를 불필요하게 채움)
    날조            [요약]·[누락 정보]에 입력에 없는 구체 사실 (detect_hallucination.py 규칙 그대로)
    출력 언어 위반  지정된 출력 언어 외의 문자 체계가 섞인 응답 (contract.py R7)
    요청·권장 반영  반드시 요청할 정보·권장 조치의 핵심어가 [누락 정보 및 권장 조치]에 있는 비율 (참고 지표)

[설계 의도]
1. 정답은 "허용 답 목록"으로 채점하고, 최선 답 일치율을 따로 보여 준다.
   경계 사례는 실무에서도 답이 갈리므로 하나만 정답으로 두면 맞는 답을 오답 처리한다.
   대신 최선 답 일치율로 "허용 범위 안에서 얼마나 좋은 쪽을 골랐는가"를 본다.
2. 위험 건(X-1~X-3)은 정답률과 별도로 건수로 센다. 평균 정답률이 높아도 Critical 한 건을 놓치면
   실무에서는 사고다. 최종 목표인 "위험 건 누락 0건"을 이 숫자로 잰다.
3. 과잉 상신을 함께 센다. X-1만 보면 "모든 글을 긴급 사인 요청으로 보내는" 모델이 만점을 받는다.
4. 형식이 깨져 필드를 읽지 못한 응답은 해당 칸을 오답으로 센다. 운영에서도 읽지 못한 응답은 처리되지 않는다.
5. 요청·권장 반영률은 핵심어 포함 여부라 표현이 다르면 놓친다. 그래서 합격 기준에 넣지 않는 참고 지표로만 둔다.
   정식 채점은 v1.4(LLM-as-judge와 사람 채점의 일치율 측정)에서 한다.
6. 날조 판정은 detect_hallucination.detect() 를 그대로 쓰고, 근거 원문은 모델에 실제로 들어간 입력
   (prompt.build_input) 전체로 한다. 공지·기존 이슈에 있는 사실을 인용한 것은 날조가 아니다.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

from triage_eval.common.detect_hallucination import detect
from triage_eval.common.paths import ROOT
from triage_eval.pipeline.contract import ENUMS_V2, NO_MODULE, parse_v2, score_format_v2, split_modules
from triage_eval.pipeline.prompt import build_input

DATASET = ROOT / "data" / "eval_v13" / "aether_raid_v13.json"
HISTORY = ROOT / "data" / "results" / "v13" / "history"
REPORT = ROOT / "report" / "eval_v13.md"

JUDGED = ["분류", "우선순위", "모듈", "재현 정보", "발생 빈도", "처리"]
CLOSING = {"개발 배정", "CS 응대", "폐기"}          # 사람 확인 없이 끝나는 처리 (X-3)
STOPWORDS = {"확인", "정보", "필요", "여부", "추가", "요청", "기존", "이슈", "관련", "내용"}


def rel(path: Path) -> str:
    """저장소 안이면 상대 경로, 밖이면(테스트 임시 폴더 등) 그대로 표시한다."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def field_correct(field: str, predicted: str | None, allowed: list[str]) -> tuple[bool, bool]:
    """(허용 답 안인가, 최선 답과 같은가)."""
    if field == "모듈":
        mods = set(split_modules(predicted or ""))
        if not allowed:  # 무관한 글 등 모듈이 없는 문항
            ok = mods <= {NO_MODULE}
            return ok, ok
        ok = bool(mods) and mods <= set(allowed)
        return ok, ok and allowed[0] in mods
    return predicted in allowed, bool(allowed) and predicted == allowed[0]


def keywords(phrase: str) -> list[str]:
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", phrase)
    return [w for w in words if w not in STOPWORDS] or words


def phrase_covered(phrase: str, text: str) -> bool:
    return any(k in text for k in keywords(phrase))


def score_one(record: dict, item: dict) -> dict:
    text = record.get("response_text", "") if record.get("success") else ""
    fmt = score_format_v2(text)
    pred = parse_v2(text)
    lb = item["labels"]
    fields = {}
    for f in JUDGED:
        ok, best = field_correct(f, pred.get(f), lb[f])
        fields[f] = {"predicted": pred.get(f), "allowed": lb[f], "ok": ok, "best": best}
    action = pred.get("처리")
    risks = {
        "X-1": "X-1" in lb["risk"] and action != "긴급 사인 요청",
        "X-2": lb["분류"][0] == "결함" and "폐기" not in lb["처리"] and action == "폐기",
        "X-3": "X-3" in lb["risk"] and action in CLOSING,
    }
    over = action == "긴급 사인 요청" and "긴급 사인 요청" not in lb["처리"]
    note = pred.get("누락 정보 및 권장 조치", "") or ""
    required = lb.get("must_request", []) + lb.get("must_recommend", [])
    covered = [p for p in required if phrase_covered(p, note)]
    halluc = detect(text, build_input(item)) if text else {"hallucinated": False, "ungrounded": [], "hedged": []}
    return {
        "eval_id": record["eval_id"], "model": record["model"], "item_id": item["id"],
        "set": item["set"], "track": item["track"], "split": item["split"], "run_index": record["run_index"],
        "success": record.get("success", False), "format": fmt, "fields": fields,
        "all_fields_ok": all(v["ok"] for v in fields.values()),
        "risk_miss": [k for k, v in risks.items() if v], "over_escalation": over,
        "required_total": len(required), "required_covered": len(covered),
        "hallucinated": halluc["hallucinated"], "ungrounded": halluc["ungrounded"],
        "elapsed_sec": record.get("elapsed_sec"), "prompt_eval_count": record.get("prompt_eval_count"),
    }


def pct(a: int, b: int):
    return round(a / b * 100, 1) if b else None


def aggregate(rows: list[dict], items: dict) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    out = {
        "n": n,
        "success": sum(r["success"] for r in rows),
        "strict_rate": pct(sum(r["format"]["strict_pass"] for r in rows), n),
        "parsable_rate": pct(sum(r["format"]["parsable_pass"] for r in rows), n),
        "field_ok_rate": {f: pct(sum(r["fields"][f]["ok"] for r in rows), n) for f in JUDGED},
        "field_best_rate": {f: pct(sum(r["fields"][f]["best"] for r in rows), n) for f in JUDGED},
        "all_fields_ok_rate": pct(sum(r["all_fields_ok"] for r in rows), n),
        "risk_miss": {k: sum(k in r["risk_miss"] for r in rows) for k in ("X-1", "X-2", "X-3")},
        "risk_items": {
            "X-1": sum("X-1" in items[r["item_id"]]["labels"]["risk"] for r in rows),
            "X-2": sum(items[r["item_id"]]["labels"]["분류"][0] == "결함"
                       and "폐기" not in items[r["item_id"]]["labels"]["처리"] for r in rows),
            "X-3": sum("X-3" in items[r["item_id"]]["labels"]["risk"] for r in rows),
        },
        "over_escalation": sum(r["over_escalation"] for r in rows),
        "hallucination_count": sum(r["hallucinated"] for r in rows),
        "language_violation": sum(not r["format"]["rules"]["R7_output_language"] for r in rows),
        "required_coverage_rate": pct(sum(r["required_covered"] for r in rows), sum(r["required_total"] for r in rows)),
        "latency_sec_mean": round(mean(r["elapsed_sec"] for r in rows if r["elapsed_sec"] is not None), 3),
        "prompt_tokens_max": max((r["prompt_eval_count"] or 0) for r in rows),
    }
    rule_fail = defaultdict(int)
    for r in rows:
        for rule in r["format"]["failed_rules"]:
            rule_fail[rule] += 1
    out["rule_failures"] = dict(rule_fail)
    return out


def latest_log() -> Path | None:
    logs = sorted(HISTORY.glob("v13_*.json"))
    return logs[-1] if logs else None


def render_report(log_path: Path, summary: dict, rows: list[dict]) -> str:
    L = [f"# v1.3 평가셋 채점 결과", "",
         f"> 실행 기록: `{rel(log_path)}` · `src/triage_eval/pipeline/score.py` 생성", ""]
    for model, by_set in summary.items():
        L += [f"## {model}", "", "| 지표 | " + " | ".join(by_set) + " |", "| :--- |" + " ---: |" * len(by_set)]

        def row(name, fn):
            L.append(f"| {name} | " + " | ".join(str(fn(v)) for v in by_set.values()) + " |")
        row("응답 수", lambda v: v["n"])
        row("STRICT / PARSABLE (%)", lambda v: f"{v['strict_rate']} / {v['parsable_rate']}")
        for f in JUDGED:
            row(f"{f} 정답률 허용 / 최선 (%)", lambda v, f=f: f"{v['field_ok_rate'][f]} / {v['field_best_rate'][f]}")
        row("전 칸 정답 (%)", lambda v: v["all_fields_ok_rate"])
        for k in ("X-1", "X-2", "X-3"):
            row(f"{k} 누락 / 측정 응답", lambda v, k=k: f"{v['risk_miss'][k]} / {v['risk_items'][k]}")
        row("과잉 상신", lambda v: v["over_escalation"])
        row("날조 응답", lambda v: v["hallucination_count"])
        row("출력 언어 위반 (R7)", lambda v: v["language_violation"])
        row("요청·권장 반영 (%, 참고)", lambda v: v["required_coverage_rate"])
        row("평균 지연 (초)", lambda v: v["latency_sec_mean"])
        row("최대 입력 토큰", lambda v: v["prompt_tokens_max"])
        L.append("")
        misses = [r for r in rows if r["model"] == model and (r["risk_miss"] or r["hallucinated"])]
        if misses:
            L += ["**위험 건·날조 상세**", "", "| 응답 | 위험 건 | 예측 처리 | 정답 처리 | 날조 |", "| :--- | :--- | :--- | :--- | :--- |"]
            for r in misses:
                f = r["fields"]["처리"]
                ents = ", ".join(e["entity"] for e in r["ungrounded"]) or "—"
                L.append(f"| {r['eval_id']} | {', '.join(r['risk_miss']) or '—'} | {f['predicted']} | {' / '.join(f['allowed'])} | {ents} |")
            L.append("")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v1.3 평가셋 정답 대조 채점")
    p.add_argument("--log", type=Path, default=None)
    p.add_argument("--no-report", action="store_true", help="report/eval_v13.md 를 쓰지 않음")
    args = p.parse_args(argv)

    log_path = args.log or latest_log()
    if not log_path or not log_path.exists():
        print("채점할 실행 기록이 없습니다. 먼저 uv run triage-run 을 실행하세요.")
        return 2
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    items = {i["id"]: i for i in json.loads(DATASET.read_text(encoding="utf-8"))["items"]}
    rows = [score_one(r, items[r["item_id"]]) for r in payload["results"]]

    summary = {}
    for model in payload["metadata"]["models"]:
        mine = [r for r in rows if r["model"] == model]
        summary[model] = {"전체": aggregate(mine, items),
                          "대표 세트": aggregate([r for r in mine if r["set"] == "representative"], items),
                          "집중 세트": aggregate([r for r in mine if r["set"] == "focused"], items)}

    out = log_path.parent.parent / f"score_{log_path.stem}.json"
    out.write_text(json.dumps({"log": log_path.name, "summary": summary, "per_response": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_report:
        REPORT.write_text(render_report(log_path, summary, rows), encoding="utf-8")

    for model, by_set in summary.items():
        a = by_set["전체"]
        print(f"[{model}] n={a['n']} STRICT {a['strict_rate']}% · 처리 정답률 {a['field_ok_rate']['처리']}% · "
              f"전 칸 정답 {a['all_fields_ok_rate']}% · X-1/X-2/X-3 누락 {a['risk_miss']} · "
              f"과잉 상신 {a['over_escalation']} · 날조 {a['hallucination_count']} · 출력 언어 위반 {a['language_violation']}")
    print(f"저장: {rel(out)}" + ("" if args.no_report else f", {rel(REPORT)}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
