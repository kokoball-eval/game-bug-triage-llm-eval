"""두 벤치마크 실행 비교 + 회귀 게이트 판정 스크립트 (v1.1).

기준선(baseline) 실행과 후보(candidate) 실행의 원본 로그를 읽어
같은 정의로 지표를 다시 계산하고, gate_criteria.toml 의 합격 기준으로 판정한다.
"프롬프트/모델/Ollama 버전을 바꿨더니 나빠졌는가?"를 사람이 눈으로 보지 않고
종료 코드 하나로 답하는 것이 목적이다.

사용법
------
    # 기본: 고정 기준선(v1.0) vs history/ 의 가장 최근 실행
    uv run python src/compare_runs.py

    # 파일 직접 지정
    uv run python src/compare_runs.py --baseline <기준선.json> --candidate <후보.json>

    # 게이트 대상 모델 지정 (기본은 gate_criteria.toml 의 target_models)
    uv run python src/compare_runs.py --model llama3.1:8b

종료 코드
---------
    0  PASS  - 모든 기준 통과
    1  FAIL  - 기준 1개 이상 미달
    2  ERROR - 비교 자체가 성립하지 않음 (문항 구성 불일치, 실행 조건 변경, 파일 없음 등)

출력
----
    표준 출력                        - 지표 비교표, 기준별 판정, 판정 변화 목록
    data/results/gate_result.json    - 기계 판독용 판정 결과
    report/regression_gate.md        - 사람이 읽는 판정 근거

[설계 의도]
1. 채점 규칙은 score_format.py 의 score_response()를 그대로 import 해서 쓴다.
   규칙을 이 파일에 다시 적으면, 한쪽만 고쳤을 때 보고서 수치와 게이트 판정이 어긋난다.
   "포맷 준수"의 정의는 저장소 안에 한 곳에만 있어야 한다.
2. 지표 정의(워밍업 제외, 속도는 회차별 단순 평균, None은 제외)는 summarize_eval.py 와 같다.
   같은 로그를 넣으면 README 표와 같은 숫자가 나와야 게이트 결과를 믿을 수 있다.
3. 기준은 절대 기준(바닥선)과 상대 기준(허용 악화폭) 두 종류다.
   - 절대만 있으면: 1.9초 → 1.99초로 느려져도 통과. 서서히 나빠지는 것을 못 잡는다.
   - 상대만 있으면: 기준선이 원래 나빴으면 "똑같이 나쁨"이 통과. 바닥이 없다.
4. 비교 전에 "비교해도 되는가"부터 확인한다 (전제조건 검사).
   문항 구성이 다르거나, 실행 조건(생성 옵션·프롬프트·문항 파일)이 바뀌었다면
   수치 차이가 모델 탓인지 조건 탓인지 구분할 수 없으므로 판정하지 않고 종료 코드 2를 낸다.
   의도한 조건 변경(예: 프롬프트 개선 효과 확인)이면 --allow-config-change 로 명시적으로 허용한다.
5. 측정값이 없으면(예: tokens_per_sec 전부 None) 통과가 아니라 실패로 본다.
   게이트는 "좋다는 증거가 있을 때만 통과"여야 한다. 증거가 없는데 통과시키면 게이트가 아니다.
6. 심각도/모듈/재현 여부 판정 변화는 목록으로만 보여주고 합격 기준에는 넣지 않는다.
   v1.0은 seed 미고정이라 같은 조건에서도 판정이 흔들린다(final_selection.md §6: 3건 변동).
   지금 이걸 기준에 넣으면 노이즈 때문에 게이트가 무의미해진다.
   → v1.2에서 "같은 seed로 돈 두 실행"일 때만 합격 기준으로 승격했다 (설계 의도 12).
7. PASS/FAIL을 종료 코드로 낸다. 사람이 출력을 읽지 않아도
   배치 파일·CI(GitHub Actions)·다른 스크립트가 "다음 단계로 가도 되는가"를 판단할 수 있다.
8. (v1.1.1) 기준 파일에 모르는 키가 있으면 판정하지 않고 종료 코드 2를 낸다.
   예를 들어 strict_rate_min 을 strict_rate_mn 으로 잘못 적으면, 그 기준은 조용히 빠진 채
   나머지로만 PASS가 난다. 게이트가 "검사를 안 하고 통과"시키는 것이 가장 위험한 실패다.
9. (v1.1.1) 변화율은 소수 둘째 자리로 반올림한 뒤 허용폭과 비교한다.
   부동소수점 오차 때문에 정확히 +20%인 변화가 20.000000000000004%로 계산되어
   "허용 20%"인데 FAIL이 나는 문제를 단위 테스트가 잡아냈다(tests/test_compare_runs.py).
10. (v1.1.1) 기본 후보는 data/results/history/ 의 가장 최근 파일이다.
   run_eval.py 가 더 이상 local_eval_results.json(문서 수치의 출처)을 기본으로 덮어쓰지 않기 때문이다.
11. (v1.2) 날조 응답 수(hallucination_count)를 절대 기준으로 둔다.
   판정은 detect_hallucination.py 의 규칙을 그대로 import 해서 쓴다(설계 의도 1과 같은 이유).
   형식이 멀쩡한 날조가 게이트를 통과하던 공백(docs/issue_log.md KL-001)을 막는다.
12. (v1.2) 판정 변화 수(verdict_change_max)는 "두 실행이 같은 seed로 돌았을 때만" 합격 기준으로 쓴다.
   seed가 같으면 같은 입력에 같은 판정이 나와야 하므로, 판정이 바뀌었다면 프롬프트·모델·환경 중
   무언가가 바뀐 것이다. seed가 다르거나 없으면 흔들림이 자연스러우므로 "생략(SKIP)"으로 표시한다.
   SKIP은 통과가 아니라 "이번 비교에서는 판정할 수 없음"이라는 뜻이라 PASS와 구분해 출력한다.
13. (v1.2) 실행 시점의 측정 환경(GPU 점유, 전원 연결)이 다르면 경고만 하고 판정은 막지 않는다.
   환경 차이는 성능 지표를 흔들 수 있지만(docs/issue_log.md OBS-001) 판정 자체를 무효로 만들지는 않는다.
"""

import argparse
import json
import sys
import tomllib
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

from score_format import parse_lines, score_response, FIELDS
from summarize_eval import rnd
from detect_hallucination import detect, load_questions

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = ROOT / "data" / "results" / "baseline" / "v1.0_local_eval_results.json"
HISTORY_DIR = ROOT / "data" / "results" / "history"
DEFAULT_CRITERIA = ROOT / "gate_criteria.toml"

VERDICT_FIELDS = ["모듈", "심각도", "재현 여부"]

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


KNOWN_CRITERIA = {
    "meta": {"version", "target_models"},
    "absolute": {"success_rate_min", "strict_rate_min", "parsable_rate_min",
                 "preamble_fail_max", "enum_fail_max", "latency_sec_max", "hallucination_max"},
    "regression": {"strict_rate_drop_max_pp", "latency_increase_max_pct",
                   "tokens_per_sec_drop_max_pct", "eval_count_increase_max_pct",
                   "verdict_change_max"},
}


class GateError(Exception):
    """판정 자체를 할 수 없는 상태. 판정하지 않고 종료 코드 2로 끝낸다."""


class ComparabilityError(GateError):
    """두 실행을 비교할 수 없는 상태 (문항 구성·실행 조건 불일치, 파일 없음 등)."""


class CriteriaError(GateError):
    """합격 기준 파일이 잘못된 상태 (모르는 섹션·키, 숫자가 아닌 기준값)."""


def validate_criteria(criteria: dict) -> None:
    """기준 파일의 오타가 기준을 조용히 꺼버리지 않도록 모르는 키를 거부한다."""
    problems = []
    for section, body in criteria.items():
        if section not in KNOWN_CRITERIA:
            problems.append(f"모르는 섹션 [{section}]")
            continue
        for key, value in body.items():
            if key not in KNOWN_CRITERIA[section]:
                problems.append(f"[{section}] 모르는 키 {key!r}")
            elif section != "meta" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                problems.append(f"[{section}] {key} 값이 숫자가 아님: {value!r}")
    if problems:
        raise CriteriaError("합격 기준 파일 오류 → " + "; ".join(problems))


def latest_history(history_dir: Path = HISTORY_DIR) -> Path:
    """history/ 에서 가장 최근 실행 파일을 고른다. 파일명의 실행 시각(YYYYMMDD_HHMMSS) 순서를 쓴다."""
    files = sorted(history_dir.glob("local_eval_results_*.json"))
    if not files:
        raise ComparabilityError(
            f"{history_dir} 에 실행 기록이 없습니다. run_eval.py 를 먼저 실행하거나 --candidate 로 지정하세요."
        )
    return files[-1]


# ── 1. 로그 읽기 ─────────────────────────────────────────────

def load_run(path: Path) -> dict:
    if not path.exists():
        raise ComparabilityError(f"파일이 없습니다: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "results" not in payload:
        raise ComparabilityError(f"run_eval.py 결과 형식이 아닙니다 (results 키 없음): {path}")
    return payload


def formal_rows(payload: dict, model: str) -> list[dict]:
    """워밍업을 제외한 해당 모델의 본 실험 회차만 돌려준다."""
    return [r for r in payload["results"] if r.get("model") == model and not r.get("is_warmup")]


# ── 2. 지표 계산 ─────────────────────────────────────────────

def compute_metrics(rows: list[dict], questions: dict | None = None) -> dict:
    """summarize_eval.py / score_format.py / detect_hallucination.py 와 같은 정의로 지표를 계산한다."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    questions = questions if questions is not None else load_questions(ROOT)
    missing = sorted({r["question_id"] for r in rows} - set(questions))
    if missing:
        raise ComparabilityError(f"questions.json 에 없는 문항이 로그에 있습니다: {missing}")

    scored = [score_response(r.get("response_text", "")) for r in rows]
    speeds = [r["tokens_per_sec"] for r in rows if r.get("tokens_per_sec") is not None]

    def rate(count: int) -> float:
        return rnd(count / n * 100, 1)

    return {
        "n": n,
        "success_rate": rate(sum(1 for r in rows if r.get("success"))),
        "strict_rate": rate(sum(1 for s in scored if s["strict_pass"])),
        "parsable_rate": rate(sum(1 for s in scored if s["parsable_pass"])),
        "preamble_fail": sum(1 for s in scored if "R1_no_preamble" in s["failed_rules"]),
        "enum_fail": sum(1 for s in scored if "R6_enum_valid" in s["failed_rules"]),
        "hallucination_count": sum(
            1 for r in rows
            if detect(r.get("response_text", ""), questions[r["question_id"]]["report_text"])["hallucinated"]
        ),
        "latency_sec": rnd(mean(r["elapsed_sec"] for r in rows), 3),
        "tokens_per_sec": rnd(mean(speeds), 2) if speeds else None,
        "eval_count": rnd(mean(r.get("eval_count", 0) for r in rows), 1),
    }


# ── 3. 전제조건 검사 ─────────────────────────────────────────

def check_comparability(base: dict, cand: dict, model: str, allow_config_change: bool) -> list[str]:
    """비교가 성립하는지 확인한다. 성립하지 않으면 예외, 주의 사항은 경고 목록으로 돌려준다."""
    warnings = []

    base_rows, cand_rows = formal_rows(base, model), formal_rows(cand, model)
    if not base_rows:
        raise ComparabilityError(f"기준선에 {model} 회차가 없습니다.")
    if not cand_rows:
        raise ComparabilityError(f"후보에 {model} 회차가 없습니다.")

    # (a) 문항·회차 구성이 같아야 평균끼리 비교가 의미 있다
    base_keys = {(r["question_id"], r.get("run_index")) for r in base_rows}
    cand_keys = {(r["question_id"], r.get("run_index")) for r in cand_rows}
    if base_keys != cand_keys:
        only_b = sorted(base_keys - cand_keys)
        only_c = sorted(cand_keys - base_keys)
        raise ComparabilityError(
            f"{model}: 문항·회차 구성이 다릅니다. 기준선에만 {only_b}, 후보에만 {only_c}"
        )

    # (b) 실행 조건. v1.1 run_eval.py 부터 metadata.run_config 에 기록된다.
    base_cfg = base.get("metadata", {}).get("run_config")
    cand_cfg = cand.get("metadata", {}).get("run_config")
    if base_cfg is None or cand_cfg is None:
        which = [name for name, cfg in (("기준선", base_cfg), ("후보", cand_cfg)) if cfg is None]
        warnings.append(
            f"{'/'.join(which)} 로그에 run_config 가 없습니다 (v1.0 이전 형식). "
            "생성 옵션·프롬프트가 같은지 코드로 검증하지 못했습니다."
        )
    else:
        diffs = []
        for key in ("options", "repeat_count", "system_prompt_sha256", "questions_sha256"):
            if base_cfg.get(key) != cand_cfg.get(key):
                diffs.append(f"{key}: {base_cfg.get(key)} → {cand_cfg.get(key)}")
        b_dig = (base_cfg.get("model_digests") or {}).get(model)
        c_dig = (cand_cfg.get("model_digests") or {}).get(model)
        if b_dig and c_dig and b_dig != c_dig:
            diffs.append(f"model_digest({model}): {b_dig} → {c_dig}")
        if diffs:
            msg = "실행 조건이 다릅니다 → " + "; ".join(diffs)
            if not allow_config_change:
                raise ComparabilityError(msg + "  (의도한 변경이면 --allow-config-change)")
            warnings.append(msg + "  (--allow-config-change 로 허용됨)")

    return warnings


# ── 4. 기준 판정 ─────────────────────────────────────────────

def _check(cid, kind, metric, rule, threshold, base_v, cand_v, passed, detail):
    return {
        "id": cid, "kind": kind, "metric": metric, "rule": rule, "threshold": threshold,
        "baseline": base_v, "candidate": cand_v, "passed": passed, "detail": detail,
    }


def seeds_match(base: dict, cand: dict) -> bool:
    """두 실행이 같은 seed 로 돌았는지. v1.2 run_eval.py --seed 로 실행한 로그에만 seeds 가 있다."""
    b = (base.get("metadata", {}).get("run_config") or {}).get("seeds")
    c = (cand.get("metadata", {}).get("run_config") or {}).get("seeds")
    return bool(b) and b == c


def environment_warnings(base: dict, cand: dict) -> list[str]:
    """실행 시점 측정 환경의 경고와 차이를 모은다 (설계 의도 13). 판정에는 영향 없음."""
    out = []
    envs = {}
    for name, payload in (("기준선", base), ("후보", cand)):
        env = (payload.get("metadata", {}).get("run_config") or {}).get("environment")
        envs[name] = env
        for w in (env or {}).get("warnings", []):
            out.append(f"{name} 실행 환경: {w}")
    b, c = envs["기준선"], envs["후보"]
    if b and c and b.get("on_ac_power") != c.get("on_ac_power"):
        out.append(f"전원 연결 상태가 다릅니다 (기준선 {b.get('on_ac_power')} → 후보 {c.get('on_ac_power')}). "
                   "성능 지표 차이가 환경 때문일 수 있습니다.")
    return out


def evaluate_gate(base_m: dict, cand_m: dict, criteria: dict,
                  verdict_change_count: int | None = None, seeded: bool = False) -> list[dict]:
    checks = []
    ab = criteria.get("absolute", {})
    rg = criteria.get("regression", {})

    # 절대 기준: (기준 키, 지표, 방향) — min 은 이상, max 는 이하여야 통과
    absolute_specs = [
        ("success_rate_min", "success_rate", "min"),
        ("strict_rate_min", "strict_rate", "min"),
        ("parsable_rate_min", "parsable_rate", "min"),
        ("preamble_fail_max", "preamble_fail", "max"),
        ("enum_fail_max", "enum_fail", "max"),
        ("latency_sec_max", "latency_sec", "max"),
        ("hallucination_max", "hallucination_count", "max"),
    ]
    for key, metric, direction in absolute_specs:
        if key not in ab:
            continue
        thr, val = ab[key], cand_m.get(metric)
        if val is None:
            checks.append(_check(key, "absolute", metric, direction, thr, base_m.get(metric), None,
                                 False, "측정값 없음 → 통과 근거가 없으므로 실패 처리"))
            continue
        ok = val >= thr if direction == "min" else val <= thr
        sign = "≥" if direction == "min" else "≤"
        checks.append(_check(key, "absolute", metric, direction, thr, base_m.get(metric), val,
                             ok, f"{val} {sign} {thr} 이어야 함"))

    # 상대 기준: 기준선 대비 악화폭. worse_if 는 값이 커질 때 나쁜지(up) 작아질 때 나쁜지(down)
    regression_specs = [
        ("strict_rate_drop_max_pp", "strict_rate", "down", "pp"),
        ("latency_increase_max_pct", "latency_sec", "up", "pct"),
        ("tokens_per_sec_drop_max_pct", "tokens_per_sec", "down", "pct"),
        ("eval_count_increase_max_pct", "eval_count", "up", "pct"),
    ]
    for key, metric, worse_if, unit in regression_specs:
        if key not in rg:
            continue
        thr = rg[key]
        b, c = base_m.get(metric), cand_m.get(metric)
        if b is None or c is None:
            checks.append(_check(key, "regression", metric, worse_if, thr, b, c,
                                 False, "기준선 또는 후보 측정값 없음 → 실패 처리"))
            continue
        if unit == "pp":
            change = c - b
        else:
            if b == 0:
                checks.append(_check(key, "regression", metric, worse_if, thr, b, c,
                                     True, "기준선 값이 0이라 변화율 계산 불가 → 판정 생략"))
                continue
            change = (c - b) / b * 100
        change = rnd(change, 2)  # 부동소수점 오차로 경계값이 뒤집히지 않게 (설계 의도 9)
        worsening = change if worse_if == "up" else -change   # 양수 = 나빠짐
        ok = worsening <= thr
        unit_label = "%p" if unit == "pp" else "%"
        checks.append(_check(key, "regression", metric, worse_if, thr, b, c, ok,
                             f"변화 {change:+.1f}{unit_label} (허용 악화폭 {thr}{unit_label})"))

    # 판정 변화: 같은 seed 일 때만 합격 기준 (설계 의도 12)
    if "verdict_change_max" in rg and verdict_change_count is not None:
        thr = rg["verdict_change_max"]
        if seeded:
            checks.append(_check("verdict_change_max", "regression", "verdict_changes", "max", thr,
                                 None, verdict_change_count, verdict_change_count <= thr,
                                 f"같은 seed 에서 판정 변화 {verdict_change_count}건 ≤ {thr} 이어야 함"))
        else:
            c = _check("verdict_change_max", "regression", "verdict_changes", "max", thr,
                       None, verdict_change_count, True,
                       f"seed 가 고정되지 않았거나 서로 달라 판정 생략 (판정 변화 {verdict_change_count}건은 참고용)")
            c["skipped"] = True
            checks.append(c)
    return checks


# ── 5. 판정 변화 (정보 제공용, 합격 기준 아님) ───────────────

def extract_verdicts(text: str) -> dict:
    vals = {lbl: val for lbl, val, _ in parse_lines((text or "").strip()) if lbl in FIELDS}
    return {f: vals.get(f, "") for f in VERDICT_FIELDS}


def verdict_changes(base_rows: list[dict], cand_rows: list[dict]) -> list[dict]:
    cand_by_key = {(r["question_id"], r.get("run_index")): r for r in cand_rows}
    changes = []
    for b in sorted(base_rows, key=lambda r: (r["question_id"], r.get("run_index"))):
        key = (b["question_id"], b.get("run_index"))
        c = cand_by_key.get(key)
        if c is None:
            continue
        bv, cv = extract_verdicts(b.get("response_text")), extract_verdicts(c.get("response_text"))
        diff = {f: {"baseline": bv[f], "candidate": cv[f]} for f in VERDICT_FIELDS if bv[f] != cv[f]}
        if diff:
            changes.append({"question_id": key[0], "run_index": key[1], "changes": diff})
    return changes


# ── 6. 출력 ──────────────────────────────────────────────────

METRIC_LABELS = [
    ("n", "표본 수"),
    ("success_rate", "호출 성공률(%)"),
    ("strict_rate", "STRICT 준수율(%)"),
    ("parsable_rate", "PARSABLE 준수율(%)"),
    ("preamble_fail", "R1 서두 사족(건)"),
    ("enum_fail", "R6 enum 이탈(건)"),
    ("hallucination_count", "날조 응답(건)"),
    ("latency_sec", "평균 지연(초)"),
    ("tokens_per_sec", "평균 속도(t/s)"),
    ("eval_count", "평균 생성 토큰"),
]


def print_model_report(model, base_m, cand_m, checks, changes, warnings):
    passed = all(c["passed"] for c in checks)
    print(f"\n{'=' * 72}\n[{model}]  판정: {'✅ PASS' if passed else '❌ FAIL'}\n{'=' * 72}")
    for w in warnings:
        print(f"  ⚠️  {w}")
    print(f"\n{'지표':<22}{'기준선':>14}{'후보':>14}")
    print("-" * 50)
    for key, label in METRIC_LABELS:
        print(f"{label:<22}{str(base_m.get(key)):>14}{str(cand_m.get(key)):>14}")
    print("\n[기준별 판정]")
    for c in checks:
        mark = "⏭️" if c.get("skipped") else ("✅" if c["passed"] else "❌")
        kind = "절대" if c["kind"] == "absolute" else "회귀"
        print(f"  {mark} [{kind}] {c['id']:<30} {c['detail']}")
    print(f"\n[판정 변화 목록] {len(changes)}건")
    for ch in changes:
        parts = [f"{f} {v['baseline']!r}→{v['candidate']!r}" for f, v in ch["changes"].items()]
        print(f"  - {ch['question_id']} run{ch['run_index']}: " + ", ".join(parts))


def write_markdown(path: Path, result: dict):
    L = []
    L.append("# 회귀 게이트 판정 결과 (Regression Gate)\n")
    L.append(f"> `src/compare_runs.py` 자동 생성 · 판정 시각 {result['judged_at']}")
    L.append(f"> 기준선: `{result['baseline_file']}`")
    L.append(f"> 후보: `{result['candidate_file']}`")
    L.append(f"> 합격 기준: `{result['criteria_file']}` (v{result['criteria_version']})\n")
    L.append(f"## 종합 판정: **{result['overall']}**\n")
    for model, m in result["models"].items():
        L.append(f"## `{model}` — {'✅ PASS' if m['passed'] else '❌ FAIL'}\n")
        for w in m["warnings"]:
            L.append(f"> ⚠️ {w}\n")
        L.append("| 지표 | 기준선 | 후보 |")
        L.append("| :--- | ---: | ---: |")
        for key, label in METRIC_LABELS:
            L.append(f"| {label} | {m['baseline_metrics'].get(key)} | {m['candidate_metrics'].get(key)} |")
        L.append("\n| 판정 | 구분 | 기준 | 내용 |")
        L.append("| :---: | :---: | :--- | :--- |")
        for c in m["checks"]:
            kind = "절대" if c["kind"] == "absolute" else "회귀"
            mark = "⏭️" if c.get("skipped") else ("✅" if c["passed"] else "❌")
            L.append(f"| {mark} | {kind} | `{c['id']}` | {c['detail']} |")
        L.append(f"\n**판정 변화 목록: {len(m['verdict_changes'])}건**\n")
        if m.get("seeded"):
            L.append("> 두 실행이 같은 seed로 돌았으므로 판정 변화는 합격 기준(`verdict_change_max`)으로 판정했습니다.\n")
        else:
            L.append("> seed가 고정되지 않았거나 서로 달라, 같은 조건에서도 판정이 흔들릴 수 있습니다. 이번 판정 변화는 참고용입니다.\n")
        if m["verdict_changes"]:
            L.append("| 문항 | 회차 | 변화 |")
            L.append("| :---: | :---: | :--- |")
            for ch in m["verdict_changes"]:
                parts = [f"{f}: `{v['baseline']}` → `{v['candidate']}`" for f, v in ch["changes"].items()]
                L.append(f"| {ch['question_id']} | {ch['run_index']} | {'<br>'.join(parts)} |")
        L.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# ── 7. 진입점 ────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="두 벤치마크 실행 비교 + 회귀 게이트")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="기준선 실행 로그")
    parser.add_argument("--candidate", type=Path, default=None,
                        help="후보 실행 로그 (기본: data/results/history/ 의 가장 최근 파일)")
    parser.add_argument("--criteria", type=Path, default=DEFAULT_CRITERIA, help="합격 기준 파일(TOML)")
    parser.add_argument("--model", action="append", help="게이트 대상 모델 (여러 번 지정 가능)")
    parser.add_argument("--allow-config-change", action="store_true",
                        help="실행 조건(옵션·프롬프트·문항·모델 digest)이 달라도 비교를 진행")
    parser.add_argument("--no-write", action="store_true", help="결과 파일을 저장하지 않고 화면에만 출력")
    args = parser.parse_args(argv)

    try:
        with args.criteria.open("rb") as f:
            criteria = tomllib.load(f)
        validate_criteria(criteria)
        if args.candidate is None:
            args.candidate = latest_history()
            print(f"후보 실행: {rel(args.candidate)} (history/ 의 가장 최근 파일)")
        base = load_run(args.baseline)
        cand = load_run(args.candidate)
        if args.baseline.resolve() == args.candidate.resolve():
            print("⚠️  기준선과 후보가 같은 파일입니다. 게이트 동작 확인용이 아니라면 파일을 확인하세요.")

        questions = load_questions(ROOT)
        models = args.model or criteria.get("meta", {}).get("target_models", [])
        if not models:
            raise ComparabilityError("게이트 대상 모델이 없습니다 (--model 또는 target_models).")

        result_models = {}
        for model in models:
            warnings = check_comparability(base, cand, model, args.allow_config_change)
            warnings += environment_warnings(base, cand)
            seeded = seeds_match(base, cand)
            b_rows, c_rows = formal_rows(base, model), formal_rows(cand, model)
            base_m, cand_m = compute_metrics(b_rows, questions), compute_metrics(c_rows, questions)
            changes = verdict_changes(b_rows, c_rows)
            checks = evaluate_gate(base_m, cand_m, criteria, verdict_change_count=len(changes), seeded=seeded)
            print_model_report(model, base_m, cand_m, checks, changes, warnings)
            result_models[model] = {
                "passed": all(c["passed"] for c in checks),
                "warnings": warnings,
                "baseline_metrics": base_m,
                "candidate_metrics": cand_m,
                "checks": checks,
                "verdict_changes": changes,
                "seeded": seeded,
            }
    except GateError as e:
        print(f"\n⛔ 판정 불가 (종료 코드 {EXIT_ERROR}): {e}")
        return EXIT_ERROR
    except (tomllib.TOMLDecodeError, json.JSONDecodeError, OSError) as e:
        print(f"\n⛔ 입력 파일을 읽지 못했습니다 (종료 코드 {EXIT_ERROR}): {e}")
        return EXIT_ERROR

    overall_pass = all(m["passed"] for m in result_models.values())
    result = {
        "judged_at": datetime.now().isoformat(),
        "overall": "PASS" if overall_pass else "FAIL",
        "baseline_file": rel(args.baseline),
        "candidate_file": rel(args.candidate),
        "criteria_file": rel(args.criteria),
        "criteria_version": criteria.get("meta", {}).get("version"),
        "criteria": criteria,
        "models": result_models,
    }

    print(f"\n종합 판정: {'✅ PASS' if overall_pass else '❌ FAIL'}")
    if not args.no_write:
        json_path = ROOT / "data" / "results" / "gate_result.json"
        md_path = ROOT / "report" / "regression_gate.md"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        write_markdown(md_path, result)
        print(f"판정 결과 저장: {json_path}\n판정 근거 문서: {md_path}")

    return EXIT_PASS if overall_pass else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
