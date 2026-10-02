"""출력 형식 v2 후처리 안전장치 — 모델 응답의 [처리] 값을 결정적 규칙으로 보정한다.

모델은 판단(분류·우선순위·재현 정보)을 하고, 그 판단에서 기계적으로 따라 나오는 처리 규칙은 코드가 강제한다.

규칙 (판정 기준서 docs/dataset/triage_guideline.md 조항)
------------------------------------------------------
    H-0   판단 필드(분류·우선순위·재현 정보)가 허용 값 밖이면 확정 처리(폐기·CS 응대·개발 배정)를 막고
          정보 요청 후 보류로 보낸다 — 판단을 읽을 수 없는 응답은 사람이 확인한다 (H-9, H-8)
    H-1   [우선순위]가 Critical이면(중복 의심 제외) [처리]는 긴급 사인 요청
    H-2   (A) 커뮤니티 제보의 결함을 개발 배정했으면 재현 대기로 되돌린다
          — 재현 정보 충분 → 등록(재현 대기), 부족 → 정보 요청 후 보류 (H-2d·H-3)
    H-2b  (B) 내부 QA·퍼블리셔 QA 작성 결함(Critical 아님, 재현 정보 충분)을 재현 대기로 보냈으면 개발 배정

[설계 의도]
1. 규칙이 보는 값은 입력 메타데이터(입력 종류, 작성자)와 모델 자신의 판단 필드뿐이다. 정답 라벨은 보지 않는다.
   실제 BTS에 붙는 코드는 정답을 모르기 때문이다. tests/test_guardrail_v2.py 가 라벨을 바꿔도 결과가 같음을 확인한다.
2. 프롬프트로 같은 규칙을 강제하면 7B 모델이 다른 판단까지 흔들리거나(v2.2: 규칙 문장 2줄 추가로 응답 29개 변화),
   처리를 정당화하려고 분류를 바꾸는 일이 생겼다(v2.2 S03: 결함 → 개선 제안). 코드 규칙은 분류를 건드리지 않으므로
   이런 우회가 생기지 않는다 (docs/issue_log.md ISSUE-007).
3. [처리] 줄만 바꾼다. 다른 필드, 줄 순서, 빈 줄은 그대로 둔다. 판단이 들어가는 필드를 코드가 바꾸면
   모델이 틀린 판단을 숨기게 되어 측정이 의미를 잃는다.
4. 형식 위반은 고치지 않는다. 허용 값 밖인 값을 비슷한 허용 값으로 바꾸지 않으며, [처리]가 허용 값이 아니거나
   [처리] 줄이 없으면 아무것도 하지 않는다. 형식 위반은 형식 채점(R2·R6)에서 그대로 드러나야 한다
   (contract.py 설계 의도 3과 같은 원칙).
   단, 판단 필드를 읽을 수 없는 응답이 확정 처리로 끝나는 것은 막는다(H-0). 고치는 것은 [처리]뿐이고
   허용 값 밖인 값은 그대로 남으므로 R6 위반은 계속 집계된다. 프롬프트 v2.3 측정에서 분류 '무관 중'(허용 값 밖)과
   함께 폐기된 결함 제보(A10)가 나와 추가했다 (docs/issue_log.md ISSUE-007).
5. 원본 응답은 버리지 않는다. 실행 기록에 raw_response_text 와 적용된 규칙을 함께 남겨,
   "모델이 얼마나 맞혔나"와 "BTS에 들어간 결과가 얼마나 맞았나"를 따로 볼 수 있게 한다.
"""

import re

from triage_eval.pipeline.contract import ENUMS_V2, parse_v2

GUARDRAIL_VERSION = "g2"  # g1: H-1·H-2·H-2b / g2: H-0 추가
QA_REPORTERS = ("내부 QA", "퍼블리셔 QA")
CLOSING = ("폐기", "CS 응대", "개발 배정")  # 사람 확인 없이 끝나는 처리 (score.py 의 X-3 정의와 같다)
JUDGED = ("분류", "우선순위", "재현 정보")
ACTION_LINE = re.compile(r"^(\s*\[처리\]\s*[:：]).*$", re.M)


def decide(track: str, reporter: str | None, pred: dict) -> tuple[str, str] | None:
    """보정이 필요하면 (규칙 이름, 새 처리 값), 아니면 None."""
    cls, pri, rep, act = pred.get("분류"), pred.get("우선순위"), pred.get("재현 정보"), pred.get("처리")
    if act not in ENUMS_V2["처리"]:
        return None  # 설계 의도 4
    if any(pred.get(f) not in ENUMS_V2[f] for f in JUDGED):
        return ("H-0", "정보 요청 후 보류") if act in CLOSING else None
    if pri == "Critical" and cls != "중복 의심":
        new, rule = "긴급 사인 요청", "H-1"
    elif track == "A" and cls == "결함" and act == "개발 배정":
        new, rule = ("등록(재현 대기)" if rep == "충분" else "정보 요청 후 보류"), "H-2"
    elif (track == "B" and reporter in QA_REPORTERS and cls == "결함"
          and rep == "충분" and act == "등록(재현 대기)"):
        new, rule = "개발 배정", "H-2b"
    else:
        return None
    return None if new == act else (rule, new)


def apply(text: str, track: str, reporter: str | None = None) -> tuple[str, list[dict]]:
    """응답 문자열을 보정한다. (보정된 응답, 적용 기록 목록)을 돌려준다."""
    pred = parse_v2(text or "")
    hit = decide(track, reporter, pred)
    if not hit:
        return text, []
    rule, new = hit
    out, n = ACTION_LINE.subn(lambda m: f"{m.group(1)} {new}", text, count=1)
    if n == 0:
        return text, []
    return out, [{"rule": rule, "field": "처리", "from": pred["처리"], "to": new}]


def apply_record(record: dict, item: dict) -> dict:
    """실행 기록 1건에 적용한다. 원본은 raw_response_text 로 보존한다 (설계 의도 5)."""
    raw = record.get("response_text", "")
    guarded, applied = (raw, []) if not record.get("success") else apply(
        raw, item["track"], item["input"].get("reporter"))
    return {**record, "raw_response_text": raw, "response_text": guarded,
            "guardrail": {"version": GUARDRAIL_VERSION, "applied": applied}}
