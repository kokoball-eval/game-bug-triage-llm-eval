"""
포맷 계약(Format Contract) 준수율 자동 채점 스크립트

목적
----
보고서에 기재하는 '규격 준수율' 수치를 사람이 눈으로 세지 않고, 원본 응답 로그에서
기계적으로 재계산한다. 어떤 회차(eval_id)가 어떤 규칙(R1~R6)에서 실패했는지까지
남겨서 채점 근거를 응답과 1:1로 연결할 수 있게 한다.

채점 규칙 (run_eval.py / 02_luna_chat.py의 SYSTEM_PROMPT가 요구한 계약 기준)
--------------------------------------------------------------------------
R1 no_preamble      : 응답이 정확히 '[요약]:' 으로 시작 (서두 인사/사족 없음)
R2 all_fields       : 5개 필드 라벨이 모두 존재
R3 field_order      : 필드 등장 순서가 규격과 동일
R4 no_blank_line    : 필드 사이에 빈 줄이 없음 (줄 단위 파서 인덱스 밀림 방지)
R5 no_stray_text    : 마지막 필드 이전 구간에 필드 라벨이 아닌 줄이 끼어들지 않음
R6 enum_valid       : [심각도], [재현 여부] 값이 프롬프트가 지정한 선택지 안에 있음

집계 기준 2종
-------------
STRICT   (R1~R6 전부 통과) : 사람이 손대지 않아도 되는 완전 규격 준수
PARSABLE (R4 제외 통과)    : 빈 줄만 허용. 정규식/필드 파서로 안전하게 파싱 가능한 수준

사용법
------
    uv run python src/score_format.py
    uv run python src/score_format.py --root <프로젝트 루트 경로>
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

FIELDS = ["요약", "모듈", "심각도", "재현 여부", "누락 정보 및 권장 조치"]

SEVERITY_ENUM = {"Blocker", "Critical", "Major", "Minor", "Trivial", "판단보류"}
REPRO_ENUM = {"발생(100%)", "간헐적", "불명확", "재현 불가"}

RULE_DESCRIPTIONS = {
    "R1_no_preamble": "응답이 '[요약]:'으로 즉시 시작 (서두 사족 없음)",
    "R2_all_fields": "5개 필드 라벨 전부 존재",
    "R3_field_order": "필드 순서가 규격과 일치",
    "R4_no_blank_line": "필드 사이 빈 줄 없음",
    "R5_no_stray_text": "필드 라벨이 아닌 줄이 중간에 끼어들지 않음",
    "R6_enum_valid": "[심각도]/[재현 여부] 값이 지정된 선택지에 포함",
}

LABEL_RE = re.compile(r"^\[(?P<label>[^\]]+)\]\s*:\s*(?P<value>.*)$")


def parse_lines(text: str):
    """응답을 줄 단위로 훑어 (라벨, 값, 원본 줄) 목록과 빈 줄 존재 여부를 돌려준다."""
    raw_lines = text.split("\n")
    parsed = []
    for idx, line in enumerate(raw_lines):
        stripped = line.strip()
        if not stripped:
            parsed.append(("__BLANK__", "", idx))
            continue
        m = LABEL_RE.match(stripped)
        if m:
            parsed.append((m.group("label").strip(), m.group("value").strip(), idx))
        else:
            parsed.append(("__TEXT__", stripped, idx))
    return parsed


def score_response(text: str) -> dict:
    text = (text or "").strip()
    parsed = parse_lines(text)

    labels_in_order = [lbl for lbl, _, _ in parsed if lbl not in ("__BLANK__", "__TEXT__")]
    values = {lbl: val for lbl, val, _ in parsed if lbl in FIELDS}

    results = {}
    reasons = {}

    # R1: 서두 사족 없이 [요약]: 으로 시작
    results["R1_no_preamble"] = text.startswith("[요약]")
    if not results["R1_no_preamble"]:
        reasons["R1_no_preamble"] = f"첫 40자: {text[:40]!r}"

    # R2: 5개 필드 전부 존재
    missing = [f for f in FIELDS if f not in labels_in_order]
    results["R2_all_fields"] = not missing
    if missing:
        reasons["R2_all_fields"] = f"누락 필드: {missing}"

    # R3: 순서 일치
    spec_labels = [lbl for lbl in labels_in_order if lbl in FIELDS]
    results["R3_field_order"] = spec_labels == FIELDS
    if not results["R3_field_order"]:
        reasons["R3_field_order"] = f"실제 순서: {spec_labels}"

    # R4: 필드 사이 빈 줄 없음
    blank_idx = [idx for lbl, _, idx in parsed if lbl == "__BLANK__"]
    results["R4_no_blank_line"] = not blank_idx
    if blank_idx:
        reasons["R4_no_blank_line"] = f"빈 줄 {len(blank_idx)}개 (줄번호 {blank_idx})"

    # R5: 마지막 필드 이전에 라벨 아닌 줄이 끼어들지 않음
    last_field_pos = None
    for pos, (lbl, _, _) in enumerate(parsed):
        if lbl == FIELDS[-1]:
            last_field_pos = pos
            break
    stray = [
        (idx, val)
        for pos, (lbl, val, idx) in enumerate(parsed)
        if lbl == "__TEXT__" and (last_field_pos is None or pos < last_field_pos)
    ]
    results["R5_no_stray_text"] = not stray
    if stray:
        reasons["R5_no_stray_text"] = f"비규격 줄 {len(stray)}개: {[s[1][:30] for s in stray]}"

    # R6: enum 준수
    sev = values.get("심각도", "")
    rep = values.get("재현 여부", "")
    sev_ok = sev in SEVERITY_ENUM
    rep_ok = rep in REPRO_ENUM
    results["R6_enum_valid"] = sev_ok and rep_ok
    if not results["R6_enum_valid"]:
        bad = []
        if not sev_ok:
            bad.append(f"심각도={sev!r}")
        if not rep_ok:
            bad.append(f"재현 여부={rep!r}")
        reasons["R6_enum_valid"] = ", ".join(bad)

    strict = all(results.values())
    parsable = all(v for k, v in results.items() if k != "R4_no_blank_line")

    return {
        "rules": results,
        "failed_rules": [k for k, v in results.items() if not v],
        "reasons": reasons,
        "strict_pass": strict,
        "parsable_pass": parsable,
    }


def collect_records(root: Path):
    records = []

    local_path = root / "data" / "results" / "local_eval_results.json"
    if local_path.exists():
        payload = json.loads(local_path.read_text(encoding="utf-8"))
        for r in payload.get("results", []):
            records.append(
                {
                    "eval_id": r.get("eval_id"),
                    "model": r.get("model"),
                    "source": "local",
                    "question_id": r.get("question_id"),
                    "run_index": r.get("run_index"),
                    "cloud_eval": r.get("cloud_eval", False),
                    "success": r.get("success"),
                    "response_text": r.get("response_text", ""),
                }
            )

    cloud_path = root / "data" / "results" / "cloud_eval_results.json"
    if cloud_path.exists():
        payload = json.loads(cloud_path.read_text(encoding="utf-8"))
        for r in payload.get("results", []):
            records.append(
                {
                    "eval_id": r.get("eval_id"),
                    "model": r.get("model"),
                    "source": "cloud",
                    "question_id": r.get("question_id"),
                    "run_index": r.get("run_index", 1),
                    "cloud_eval": True,
                    "success": r.get("success"),
                    "response_text": r.get("response_text", ""),
                }
            )

    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None, help="프로젝트 루트 (기본: 스크립트 상위 폴더)")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    records = collect_records(root)
    if not records:
        raise SystemExit(f"결과 파일을 찾지 못했습니다: {root / 'data' / 'results'}")

    scored = []
    by_model = defaultdict(lambda: {"total": 0, "strict": 0, "parsable": 0, "rule_fail": defaultdict(int)})
    by_model_cloud_subset = defaultdict(lambda: {"total": 0, "strict": 0, "parsable": 0})

    for rec in records:
        s = score_response(rec["response_text"])
        row = {**{k: v for k, v in rec.items() if k != "response_text"}, **s}
        scored.append(row)

        agg = by_model[rec["model"]]
        agg["total"] += 1
        agg["strict"] += int(s["strict_pass"])
        agg["parsable"] += int(s["parsable_pass"])
        for rule in s["failed_rules"]:
            agg["rule_fail"][rule] += 1

        if rec["cloud_eval"]:
            sub = by_model_cloud_subset[rec["model"]]
            sub["total"] += 1
            sub["strict"] += int(s["strict_pass"])
            sub["parsable"] += int(s["parsable_pass"])

    # ── 콘솔 요약 ─────────────────────────────────────────────
    print("=" * 78)
    print("포맷 계약 준수율 자동 채점 결과")
    print("=" * 78)
    print("\n[전체 집계]")
    print(f"{'모델':<16}{'표본(n)':>8}{'STRICT':>14}{'PARSABLE':>14}")
    for model, agg in by_model.items():
        st = f"{agg['strict']}/{agg['total']} ({agg['strict']/agg['total']*100:.0f}%)"
        pa = f"{agg['parsable']}/{agg['total']} ({agg['parsable']/agg['total']*100:.0f}%)"
        print(f"{model:<16}{agg['total']:>8}{st:>14}{pa:>14}")

    print("\n[Cloud 공통 5문항 부분집합]")
    for model, sub in by_model_cloud_subset.items():
        st = f"{sub['strict']}/{sub['total']} ({sub['strict']/sub['total']*100:.0f}%)"
        pa = f"{sub['parsable']}/{sub['total']} ({sub['parsable']/sub['total']*100:.0f}%)"
        print(f"  {model:<16} STRICT {st:<14} PARSABLE {pa}")

    print("\n[규칙별 실패 건수]")
    for model, agg in by_model.items():
        print(f"  {model}")
        if not agg["rule_fail"]:
            print("    실패 없음")
        for rule, cnt in sorted(agg["rule_fail"].items()):
            print(f"    {rule:<20} {cnt:>3}건  ({RULE_DESCRIPTIONS[rule]})")

    print("\n[실패 회차 상세]")
    any_fail = False
    for row in scored:
        if row["failed_rules"]:
            any_fail = True
            print(f"  - {row['eval_id']}: {', '.join(row['failed_rules'])}")
            for rule, why in row["reasons"].items():
                print(f"      · {rule}: {why}")
    if not any_fail:
        print("  전 회차 통과")

    # ── 결과 저장 ─────────────────────────────────────────────
    out_dir = root / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "format_compliance.json"

    payload = {
        "metadata": {
            "description": "포맷 계약(5개 필드) 준수율 자동 채점 결과",
            "rules": RULE_DESCRIPTIONS,
            "severity_enum": sorted(SEVERITY_ENUM),
            "reproducibility_enum": sorted(REPRO_ENUM),
            "criteria": {
                "STRICT": "R1~R6 전부 통과",
                "PARSABLE": "R4(빈 줄 없음)를 제외한 전 규칙 통과",
            },
        },
        "summary": {
            model: {
                "n": agg["total"],
                "strict_pass": agg["strict"],
                "strict_rate": round(agg["strict"] / agg["total"] * 100, 1),
                "parsable_pass": agg["parsable"],
                "parsable_rate": round(agg["parsable"] / agg["total"] * 100, 1),
                "rule_failures": dict(agg["rule_fail"]),
            }
            for model, agg in by_model.items()
        },
        "summary_cloud_subset": {
            model: {
                "n": sub["total"],
                "strict_pass": sub["strict"],
                "strict_rate": round(sub["strict"] / sub["total"] * 100, 1),
                "parsable_pass": sub["parsable"],
                "parsable_rate": round(sub["parsable"] / sub["total"] * 100, 1),
            }
            for model, sub in by_model_cloud_subset.items()
        },
        "per_response": scored,
    }

    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장 완료: {out_path}")


if __name__ == "__main__":
    main()
