"""환각(입력에 없는 구체 사실) 자동 탐지 스크립트 (v1.2).

트리아지 응답에 **입력 리포트에 없는 구체적 사실**이 들어 있는지 규칙 기반으로 찾는다.
v1.0과 9/30 재실행에서 Llama-3.1-8B가 단문 리포트 "크래시남"에 대해
"Windows 10, Intel Core i5, GTX 1660 Ti", "WASD 키 반복 입력", "게임 시작 후 10분 이내"처럼
없는 기기·조작·시간 조건을 지어냈는데, 형식은 정상이라 회귀 게이트를 통과했다(docs/issue_log.md KL-001).
이 스크립트는 그 공백을 메우기 위한 것이다.

탐지 방식
---------
1. 응답의 [요약]과 [누락 정보 및 권장 조치] 필드에서 "구체 사실" 후보를 정규식으로 뽑는다.
   (심각도·재현 여부 같은 선택지 필드는 제외. "발생(100%)"의 100%를 사실로 오인하지 않기 위해)
2. 각 후보가 입력 리포트에 근거가 있는지(grounded) 확인한다.
3. 근거가 없더라도 "요청·예시 문맥"이면 날조로 세지 않는다.
   - 예: "OS: Windows 10/11/Android 중 택1 확인 필요" → 정보를 요청하는 것이지 단정이 아님

구체 사실 범주
--------------
    os        OS와 버전           Windows 10, iOS 17.4, Android 14
    hardware  PC 부품·칩셋        NVIDIA, GTX 1660 Ti, Core i5, 스냅드래곤
    device    모바일 기기 모델    갤럭시 S21, iPhone 15
    version   앱·빌드 버전        v2.3.1
    quantity  시간·횟수·수치      5초, 10분, 3회, 60fps
    input     조작 입력           WASD, Space 키, 마우스 우클릭

사용법
------
    uv run bench-hallucination                  # 문서 기준 로그 + Cloud 로그
    uv run bench-hallucination --log <로그.json>  # 특정 실행 로그

출력
----
    data/results/hallucination_report.json   - 회차별 탐지 결과
    표준 출력                                 - 모델별 집계와 탐지 상세

[설계 의도]
1. LLM이 아니라 규칙으로 판정한다.
   판정 자체가 매번 같아야 회귀 게이트의 기준으로 쓸 수 있다. 다른 LLM에게 "날조인가?"를 물으면
   채점기도 흔들린다. LLM 채점(LLM-as-judge)은 v1.4에서 사람 채점과의 일치율을 잰 뒤에 도입한다.
2. "구체 사실"만 본다. 문장 의미의 날조는 보지 않는다.
   "전투 모드에서 캐릭터가 무한히 이동"처럼 요약 내용 자체를 지어낸 경우는 이 방식으로 못 잡는다.
   의미 비교는 정상적인 바꿔 말하기("크래시남" → "앱 강제 종료")까지 날조로 오판하기 쉽다.
   대신 트래커를 가장 크게 오염시키는 기기·환경·조건 날조를 오탐 없이 잡는 데 집중했다.
3. 근거 확인은 "글자 그대로 일치"가 아니라 "구성 토큰이 모두 입력에 있는가"로 한다.
   입력이 "갤럭시 기종(S21)"이고 응답이 "갤럭시 S21"이면 근거가 있는 것으로 본다.
   단, 수치(quantity)는 "5초"와 "15초"를 구분해야 하므로 붙여 쓴 형태가 그대로 있어야 한다.
4. 요청·예시 문맥은 따로 기록(hedged)하되 날조로 세지 않는다.
   "확인이 필요한 정보"를 묻는 것은 트리아지 응답의 정상 동작이다.
   이를 날조로 세면 역질문을 잘하는 모델이 벌점을 받는다.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from triage_eval.common.paths import ROOT
from triage_eval.common.score_format import parse_lines

SCANNED_FIELDS = ("요약", "누락 정보 및 권장 조치")

ENTITY_PATTERNS = {
    "os": r"(?:windows|win)\s?\d+(?:\.\d+)?|ios\s?\d+(?:\.\d+)*|(?:android|안드로이드)\s?\d+(?:\.\d+)?|macos(?:\s?\d+)?",
    "hardware": r"nvidia|geforce|(?:gtx|rtx|rx)\s?\d{3,4}(?:\s?ti)?|radeon|intel|core\s?i\d|ryzen(?:\s?\d)?"
                r"|snapdragon|스냅드래곤|exynos|엑시노스",
    "device": r"(?:galaxy|갤럭시)\s?[a-z]{0,2}\d+|(?:iphone|아이폰)\s?\d+|ipad|아이패드|pixel\s?\d+",
    "version": r"v\d+(?:\.\d+)+|(?<![\d.])\d+\.\d+\.\d+(?![\d.])",
    # 앞에 숫자·마침표가 붙으면 버전 번호의 일부이므로 제외 ("v2.3.1 회귀"의 "3.1 회"),
    # "회귀"의 "회"는 횟수 단위가 아니므로 제외
    "quantity": r"(?<![\d.])\d+(?:\.\d+)?\s?(?:초|분|시간|프레임|fps|mb|gb|회(?!귀)|번째)",
    "input": r"wasd|(?:ctrl|alt|shift|esc|space|스페이스(?:바)?|f\d{1,2})\s?키?|[a-z]\s?키|마우스\s?(?:좌|우)?클릭",
}
COMPILED = {cat: re.compile(p) for cat, p in ENTITY_PATTERNS.items()}

# 요청·예시 문맥 표지 (설계 의도 4)
HEDGE_BEFORE = re.compile(r"(?:예:|예\)|\(예|예를 들|예시|e\.g\.)[^.\n]{0,15}$")
HEDGE_AFTER = re.compile(r"^[^.\n]{0,20}(?:중 택|중 하나|중에서|또는|여부 확인|인지 확인)")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def _tokens(entity: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+(?:\.\d+)*|[가-힣]+", entity.lower())


def is_grounded(entity: str, category: str, report_text: str) -> bool:
    """후보가 입력 리포트에 근거가 있는지 (설계 의도 3)."""
    source = _normalize(report_text)
    if category != "quantity" and _normalize(entity) in source:
        return True
    if category == "quantity":
        # "5초"가 "15초" 안에 들어 있다고 근거로 치지 않는다 (앞에 숫자가 붙으면 다른 수치)
        return re.search(r"(?<![\d.])" + re.escape(_normalize(entity)), source) is not None
    return all(tok in source for tok in _tokens(entity))


def is_hedged(text: str, start: int, end: int) -> bool:
    """후보가 슬래시 나열·예시·선택지 같은 요청 문맥 안에 있는지 (설계 의도 4)."""
    before, after = text[:start], text[end:]
    if before.rstrip().endswith("/") or after.lstrip().startswith("/"):
        return True
    return bool(HEDGE_BEFORE.search(before) or HEDGE_AFTER.search(after))


def detect(response_text: str, report_text: str) -> dict:
    """응답 1건을 검사한다. hallucinated 가 True 이면 근거 없는 구체 사실이 1개 이상 있다."""
    fields = {lbl: val for lbl, val, _ in parse_lines((response_text or "").strip()) if lbl in SCANNED_FIELDS}
    ungrounded, hedged = [], []
    for field, value in fields.items():
        lowered = value.lower()
        for category, pattern in COMPILED.items():
            for m in pattern.finditer(lowered):
                entity = m.group(0).strip()
                if is_grounded(entity, category, report_text):
                    continue
                item = {"category": category, "entity": value[m.start():m.end()].strip(), "field": field}
                (hedged if is_hedged(lowered, m.start(), m.end()) else ungrounded).append(item)
    return {"hallucinated": bool(ungrounded), "ungrounded": ungrounded, "hedged": hedged}


def load_questions(root: Path = ROOT) -> dict:
    payload = json.loads((root / "data" / "questions.json").read_text(encoding="utf-8"))
    return {q["id"]: q for q in payload["questions"]}


def scan_log(path: Path, questions: dict) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for r in payload.get("results", []):
        if r.get("is_warmup"):
            continue
        q = questions.get(r.get("question_id"))
        if q is None:
            raise SystemExit(f"{path}: 문항 {r.get('question_id')} 가 questions.json 에 없습니다.")
        rows.append({
            "eval_id": r.get("eval_id"),
            "model": r.get("model"),
            "question_id": r.get("question_id"),
            "run_index": r.get("run_index", 1),
            **detect(r.get("response_text", ""), q["report_text"]),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="환각(근거 없는 구체 사실) 자동 탐지")
    parser.add_argument("--log", type=Path, action="append",
                        help="검사할 실행 로그 (기본: local_eval_results.json + cloud_eval_results.json)")
    parser.add_argument("--no-write", action="store_true", help="결과 파일을 저장하지 않음")
    args = parser.parse_args(argv)

    results_dir = ROOT / "data" / "results"
    logs = args.log or [p for p in (results_dir / "local_eval_results.json",
                                    results_dir / "cloud_eval_results.json") if p.exists()]
    questions = load_questions()

    rows = []
    for log in logs:
        rows.extend(dict(r, source=str(log.name)) for r in scan_log(log, questions))

    summary = defaultdict(lambda: {"n": 0, "hallucinated": 0, "hedged_mentions": 0})
    for r in rows:
        s = summary[r["model"]]
        s["n"] += 1
        s["hallucinated"] += int(r["hallucinated"])
        s["hedged_mentions"] += len(r["hedged"])

    print("=" * 72)
    print("환각(근거 없는 구체 사실) 자동 탐지 결과")
    print("=" * 72)
    print(f"\n{'모델':<18}{'표본(n)':>8}{'날조 응답':>12}{'요청 문맥(참고)':>18}")
    for model, s in summary.items():
        print(f"{model:<18}{s['n']:>8}{s['hallucinated']:>12}{s['hedged_mentions']:>18}")

    print("\n[날조 탐지 상세]")
    flagged = [r for r in rows if r["hallucinated"]]
    for r in flagged:
        items = ", ".join(f"{u['entity']}({u['category']})" for u in r["ungrounded"])
        print(f"  - {r['eval_id']}: {items}")
    if not flagged:
        print("  탐지 없음")

    if not args.no_write:
        out = results_dir / "hallucination_report.json"
        out.write_text(json.dumps({
            "metadata": {
                "description": "응답의 [요약]·[누락 정보] 필드에서 입력에 근거 없는 구체 사실을 규칙 기반으로 탐지",
                "categories": ENTITY_PATTERNS,
                "logs": [str(p.name) for p in logs],
            },
            "summary": dict(summary),
            "per_response": rows,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
