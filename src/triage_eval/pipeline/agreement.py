"""v1.5 라벨 일치율 — 채점자 판정 시트를 정답 라벨과 대조해 칸별 일치율·κ·Critical 인식률을 계산하고 판단 기준으로 판정한다.

계획(사전 등록): report/label_agreement_v15_plan.md · 기준: label_agreement_v15.toml

사용법
------
    uv run triage-agreement --sheet <채점자1 시트.xlsx> --sheet <채점자2 시트.xlsx>

종료 코드
---------
    0  모든 칸·Critical 기준 통과   1  기준에 못 미친 칸이 있음(불일치 검토 대상)
    2  판정 불가 (빈칸·선택지 밖 값, 채점자 순서 뒤바뀜, 대응표와 평가셋 불일치, 기준 파일 오류)

출력
----
    data/label_agreement/agreement_v15.json   기계 판독용 결과 (채점자 답 원본 포함)
    report/label_agreement_v15.md              판정표와 불일치 검토표

[설계 의도]
1. 채점자 답은 모델 응답과 같은 함수(score.field_correct)로 정답 라벨과 대조한다. 사람과 모델을 같은 잣대로 재야
   "모델 정답률"과 "사람 일치율"을 나란히 볼 수 있다. 모듈은 모듈1·모듈2를 " / "로 합쳐 같은 규칙(고른 모듈이 모두 허용 답 안)으로 본다.
2. κ는 Cohen κ다. 정답 대비 κ는 채점자 답과 정답 최선 답(허용 답의 첫 값)을, 채점자끼리 κ는 두 채점자의 답을 비교한다.
   모듈의 κ는 모듈1과 최선 모듈로 계산한다. 결함이 아닌 글처럼 허용 모듈이 없는 문항의 최선 모듈은 "해당 없음"이다.
3. 두 답이 모두 한 값뿐이라 우연 일치 확률이 1이면 κ는 정의되지 않는다(None). 이때 그 칸은 허용 답 일치율로만 판정하고 결과에 적는다.
4. 시트를 읽을 때 빈칸이나 선택지 밖 값이 하나라도 있으면 계산하지 않는다(종료 코드 2). 채점자에게 모든 칸을 고르도록 안내했고,
   빈칸을 오답이나 제외로 조용히 처리하면 일치율이 왜곡된다. 무엇이 빠졌는지 문항·칸을 모두 알려 준다.
5. 시트의 "시작하기" 탭에 적힌 채점자 이름이 기준 파일의 순서와 다르면 계산하지 않는다. 시니어·주니어 시트가 뒤바뀌는 실수를 막는다.
6. 번호 대응표가 만들어질 때의 평가셋 지문과 지금 평가셋 지문이 다르면 계산하지 않는다. 라벨이 바뀐 평가셋으로 대조하면 판정 수집 시점의 기준과 달라진다.
7. 불일치 검토표에는 정답 라벨·채점자 답·확신도·메모·판정 근거(rationale)만 넣고 모델 응답은 넣지 않는다(계획 §5 — 모델이 맞히는 쪽으로 라벨을 고치지 않게).
8. 기준 파일에 모르는 섹션·키·칸이 있거나 필요한 키가 없으면 판정하지 않는다(v1.1.1 ISSUE-003).
"""

import argparse
import hashlib
import json
import sys
import tomllib
from collections import Counter
from pathlib import Path

from triage_eval.common.paths import ROOT
from triage_eval.pipeline.contract import ENUMS_V2, MODULES, NO_MODULE
from triage_eval.pipeline.gate import GateError
from triage_eval.pipeline.score import JUDGED, field_correct, rel

CRITERIA = ROOT / "label_agreement_v15.toml"
DATASET = ROOT / "data" / "eval_v14" / "aether_raid_v14.json"
RESULT_JSON = ROOT / "data" / "label_agreement" / "agreement_v15.json"
REPORT = ROOT / "report" / "label_agreement_v15.md"

ANSWER_COLS = {"분류": "분류", "모듈1": "모듈", "우선순위": "우선순위", "재현 정보": "재현 정보", "발생 빈도": "발생 빈도", "처리": "처리"}
VALID = {**ENUMS_V2, "모듈1": MODULES + [NO_MODULE], "모듈2 (선택)": MODULES, "확신도": ["높음", "보통", "낮음"]}
KNOWN = {"meta": {"version", "dataset", "split", "raters", "blind_map"}, "field": set(JUDGED), "critical": {"recall_min"}}
FIELD_KEYS = {"allowed_rate_min", "kappa_min"}


# ── 기준 파일 ────────────────────────────────────────────────

def load_criteria(path: Path = CRITERIA) -> dict:
    """설계 의도 8."""
    if not path.exists():
        raise GateError(f"기준 파일이 없습니다: {path}")
    c = tomllib.loads(path.read_text(encoding="utf-8"))
    problems = [f"모르는 섹션 [{s}]" for s in c if s not in KNOWN]
    problems += [f"[{s}] 모르는 키 {k!r}" for s in ("meta", "field", "critical") for k in c.get(s, {}) if k not in KNOWN[s]]
    problems += [f"[field.{f}] 모르는 키 {k!r}" for f, body in c.get("field", {}).items() if f in KNOWN["field"]
                 for k in body if k not in FIELD_KEYS]
    problems += [f"[{s}] {k} 가 없습니다" for s in ("meta", "critical") for k in KNOWN[s] if k not in c.get(s, {})]
    problems += [f"[field.{f}] 이 없습니다" for f in JUDGED if f not in c.get("field", {})]
    problems += [f"[field.{f}] allowed_rate_min 이 없습니다" for f, body in c.get("field", {}).items() if "allowed_rate_min" not in body]
    if problems:
        raise GateError("기준 파일 오류 → " + "; ".join(problems))
    return c


# ── 시트 읽기 ────────────────────────────────────────────────

def read_sheet(path: Path, expected_rater: str) -> dict[str, dict]:
    """설계 의도 4·5 — {번호: {칸: 값, 확신도, 메모}}. 빈칸·선택지 밖 값·채점자 뒤바뀜이면 GateError."""
    from openpyxl import load_workbook   # 개발 의존성 — 이 기능을 쓸 때만 불러온다

    if not path.exists():
        raise GateError(f"판정 시트가 없습니다: {path}")
    wb = load_workbook(path, data_only=True)
    banner = str(wb["시작하기"]["A2"].value or "")
    if not banner.startswith(expected_rater + " "):
        raise GateError(f"{path.name} 는 {expected_rater} 시트가 아닙니다 (시트 표시: {banner.split(' ')[0] or '없음'}). "
                        "--sheet 순서를 기준 파일의 raters 순서와 맞추세요")
    ws = wb["판정"]
    header = [c.value for c in ws[1]]
    out, problems = {}, []
    for row in ws.iter_rows(min_row=2, values_only=True):
        v = dict(zip(header, row))
        q = v.get("번호")
        if not q:
            continue
        ans = {}
        for col, field in ANSWER_COLS.items():
            val = (str(v.get(col)).strip() if v.get(col) is not None else "")
            if not val:
                problems.append(f"{q} {col} 빈칸")
            elif val not in VALID[col if col in VALID else field]:
                problems.append(f"{q} {col} 선택지 밖 값 {val!r}")
            ans[field] = val
        m2 = str(v.get("모듈2 (선택)") or "").strip()
        if m2 and m2 not in VALID["모듈2 (선택)"]:
            problems.append(f"{q} 모듈2 선택지 밖 값 {m2!r}")
        conf = str(v.get("확신도") or "").strip()
        if conf and conf not in VALID["확신도"]:
            problems.append(f"{q} 확신도 선택지 밖 값 {conf!r}")
        ans["모듈1"] = ans["모듈"]
        if m2 and m2 != ans["모듈"]:
            ans["모듈"] = f"{ans['모듈']} / {m2}"   # 설계 의도 1
        out[q] = {**ans, "확신도": conf or None, "메모": str(v.get("메모") or "").strip() or None}
    if problems:
        raise GateError(f"{path.name} 판정 시트에 고칠 곳이 {len(problems)}곳 있습니다 → " + "; ".join(problems))
    return out


def load_items(crit: dict) -> tuple[dict[str, dict], dict[str, str]]:
    """설계 의도 6 — (번호 → 문항, 번호 → 문항 ID)."""
    bmap = json.loads((ROOT / crit["meta"]["blind_map"]).read_text(encoding="utf-8"))
    sha = hashlib.sha256(DATASET.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    if bmap["dataset_sha256"] != sha:
        raise GateError("번호 대응표를 만든 뒤 평가셋이 바뀌었습니다. 판정 수집 시점의 라벨로 대조할 수 없습니다")
    items = {i["id"]: i for i in json.loads(DATASET.read_text(encoding="utf-8"))["items"]}
    return {q: items[i] for q, i in bmap["map"].items()}, bmap["map"]


# ── 지표 ─────────────────────────────────────────────────────

def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """설계 의도 2·3 — 우연 일치 확률이 1이면 None."""
    n = len(a)
    if n == 0 or n != len(b):
        raise ValueError("두 판정 목록의 길이가 같아야 합니다")
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe >= 1.0:
        return None
    return round((po - pe) / (1 - pe), 4)


def best(item: dict, field: str) -> str:
    allowed = item["labels"][field]
    return allowed[0] if allowed else (NO_MODULE if field == "모듈" else "해당 없음")


def kappa_value(ans: dict, field: str) -> str:
    return ans["모듈1"] if field == "모듈" else ans[field]


def rater_stats(answers: dict[str, dict], items: dict[str, dict]) -> dict:
    qs = sorted(items)
    out = {}
    for f in JUDGED:
        ok = [field_correct(f, answers[q][f], items[q]["labels"][f])[0] for q in qs]
        out[f] = {"allowed_ok": sum(ok), "n": len(qs), "allowed_rate": round(sum(ok) / len(qs) * 100, 2),
                  "kappa": cohen_kappa([kappa_value(answers[q], f) for q in qs], [best(items[q], f) for q in qs])}
    crit = [q for q in qs if "X-1" in items[q]["labels"]["risk"]]
    hit = [q for q in crit if answers[q]["우선순위"] == "Critical" or answers[q]["처리"] == "긴급 사인 요청"]
    out["critical"] = {"n": len(crit), "hit": len(hit), "recall": round(len(hit) / len(crit) * 100, 2) if crit else None,
                       "missed": [q for q in crit if q not in hit]}
    return out


def judge(stats: dict[str, dict], crit: dict) -> dict:
    """계획 §4 — 칸마다 두 채점자 모두 기준을 넘어야 신뢰."""
    fields = {}
    for f in JUDGED:
        rule = crit["field"][f]
        per = {}
        for r, s in stats.items():
            rate_ok = s[f]["allowed_rate"] >= rule["allowed_rate_min"]
            k = s[f]["kappa"]
            kappa_ok = True if "kappa_min" not in rule or k is None else k >= rule["kappa_min"]
            per[r] = {"allowed_rate_ok": rate_ok, "kappa_ok": kappa_ok, "kappa_undefined": k is None and "kappa_min" in rule}
        fields[f] = {"trusted": all(p["allowed_rate_ok"] and p["kappa_ok"] for p in per.values()), "per_rater": per}
    critical = {r: s["critical"]["recall"] is not None and s["critical"]["recall"] >= crit["critical"]["recall_min"]
                for r, s in stats.items()}
    return {"fields": fields, "critical": {"passed": all(critical.values()), "per_rater": critical}}


def disagreements(answers: dict[str, dict[str, dict]], items: dict[str, dict], qmap: dict[str, str]) -> list[dict]:
    """설계 의도 7 — 한 채점자라도 허용 답 밖이거나 Critical 문항을 Critical로 보지 않은 (문항, 칸). 모델 응답은 넣지 않는다."""
    rows = []
    for q in sorted(items):
        item = items[q]
        for f in JUDGED:
            outs = {r: not field_correct(f, a[q][f], item["labels"][f])[0] for r, a in answers.items()}
            if any(outs.values()):
                rows.append({"번호": q, "문항": qmap[q], "칸": f, "정답 허용 답": item["labels"][f] or [NO_MODULE],
                             "채점자 답": {r: a[q][f] for r, a in answers.items()},
                             "허용 답 밖": [r for r, o in outs.items() if o],
                             "확신도": {r: a[q]["확신도"] for r, a in answers.items()},
                             "메모": {r: a[q]["메모"] for r, a in answers.items()},
                             "채점자끼리 다름": len({a[q][f] for a in answers.values()}) > 1,
                             "근거": item.get("rationale")})
    return rows


# ── 출력 ─────────────────────────────────────────────────────

def render(raters, stats, between, verdict, rows, crit) -> str:
    mark = lambda ok: "✅" if ok else "❌"   # noqa: E731
    L = ["# v1.5 라벨 일치율 판정", "",
         "> 계획 [`label_agreement_v15_plan.md`](label_agreement_v15_plan.md) · 기준 `label_agreement_v15.toml` · "
         "`src/triage_eval/pipeline/agreement.py` 생성", "",
         "## 칸별 판정", "",
         "| 칸 | 기준 | " + " | ".join(f"{r} 일치율 / κ" for r in raters) + " | 채점자끼리 κ | 판정 |",
         "| :--- | :--- | " + " | ".join(":---:" for _ in raters) + " | :---: | :---: |"]
    for f in JUDGED:
        rule = crit["field"][f]
        lim = f"일치율 ≥ {rule['allowed_rate_min']}%" + (f", κ ≥ {rule['kappa_min']}" if "kappa_min" in rule else "")
        cells = [f"{stats[r][f]['allowed_rate']}% / {stats[r][f]['kappa'] if stats[r][f]['kappa'] is not None else '정의 안 됨'}"
                 for r in raters]
        L.append(f"| {f} | {lim} | " + " | ".join(cells) + f" | {between[f] if between[f] is not None else '정의 안 됨'} | "
                 + ("신뢰 ✅" if verdict["fields"][f]["trusted"] else "검토 ❌") + " |")
    L += ["", "## Critical 인식률", "", "| 채점자 | Critical로 봄 / 측정 문항 | 인식률 | 기준 | 결과 |", "| :--- | :---: | :---: | :---: | :---: |"]
    for r in raters:
        c = stats[r]["critical"]
        L.append(f"| {r} | {c['hit']} / {c['n']} | {c['recall']}% | ≥ {crit['critical']['recall_min']}% | "
                 f"{mark(verdict['critical']['per_rater'][r])} |")
    L += ["", f"## 불일치 검토표 ({len(rows)}건)", "",
          "한 채점자라도 정답 허용 답 밖으로 판정한 (문항, 칸)이다. 모델 응답은 넣지 않았다(계획 §5).", "",
          "| 번호 | 문항 | 칸 | 정답 허용 답 | " + " | ".join(raters) + " | 확신도 | 메모 |",
          "| :--- | :--- | :--- | :--- | " + " | ".join(":---" for _ in raters) + " | :--- | :--- |"]
    for x in rows:
        answers = [f"{x['채점자 답'][r]}{' ✗' if r in x['허용 답 밖'] else ''}" for r in raters]
        conf = " / ".join(str(x["확신도"][r] or "—") for r in raters)
        memo = " / ".join(str(x["메모"][r] or "—").replace("|", "／") for r in raters)
        L.append(f"| {x['번호']} | {x['문항']} | {x['칸']} | {', '.join(x['정답 허용 답'])} | " + " | ".join(answers)
                 + f" | {conf} | {memo} |")
    return "\n".join(L) + "\n"


def run(sheets: list[Path], crit: dict, write: bool = True) -> int:
    raters = crit["meta"]["raters"]
    if len(sheets) != len(raters):
        raise GateError(f"판정 시트는 {len(raters)}개({', '.join(raters)} 순서)여야 합니다")
    items, qmap = load_items(crit)
    answers = {r: read_sheet(p, r) for r, p in zip(raters, sheets)}
    for r, a in answers.items():
        if sorted(a) != sorted(items):
            raise GateError(f"{r} 시트의 문항 번호가 대응표와 다릅니다")
    stats = {r: rater_stats(a, items) for r, a in answers.items()}
    qs = sorted(items)
    between = {f: cohen_kappa(*[[kappa_value(answers[r][q], f) for q in qs] for r in raters]) for f in JUDGED}
    verdict = judge(stats, crit)
    rows = disagreements(answers, items, qmap)
    ok = all(v["trusted"] for v in verdict["fields"].values()) and verdict["critical"]["passed"]

    for f in JUDGED:
        print(f"  {'✅' if verdict['fields'][f]['trusted'] else '❌'} {f}: " +
              " · ".join(f"{r} {stats[r][f]['allowed_rate']}% κ {stats[r][f]['kappa']}" for r in raters))
    print(f"  {'✅' if verdict['critical']['passed'] else '❌'} Critical 인식률: " +
          " · ".join(f"{r} {stats[r]['critical']['hit']}/{stats[r]['critical']['n']}" for r in raters))
    print(f"  불일치 검토 대상 {len(rows)}건 (문항 × 칸)")
    if write:
        RESULT_JSON.parent.mkdir(parents=True, exist_ok=True)
        RESULT_JSON.write_text(json.dumps({"raters": raters, "sheets": [rel(p) for p in sheets], "stats": stats,
                                           "between_raters_kappa": between, "verdict": verdict, "disagreements": rows,
                                           "answers": answers}, ensure_ascii=False, indent=2), encoding="utf-8")
        REPORT.write_text(render(raters, stats, between, verdict, rows, crit), encoding="utf-8")
        print(f"\n저장: {rel(RESULT_JSON)}, {rel(REPORT)}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v1.5 라벨 일치율 판정")
    p.add_argument("--sheet", type=Path, action="append", required=True, help="채점자 판정 시트 (기준 파일의 raters 순서대로)")
    p.add_argument("--criteria", type=Path, default=CRITERIA)
    p.add_argument("--no-write", action="store_true")
    args = p.parse_args(argv)
    try:
        return run(args.sheet, load_criteria(args.criteria), write=not args.no_write)
    except GateError as e:
        print(f"판정 불가: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
