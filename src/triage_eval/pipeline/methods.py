"""v1.4 방법 비교의 방법 정의 — M1(판정 예시)과 M2(Critical 체크리스트).

계획: report/method_comparison_v14_plan.md (측정 전 확정, 2026-10-04)

    m0    기준선. 프롬프트 v2.3 + 형식 재요청 + 폐기 확인 + 후처리 안전장치 g2
    m1    m0 + 판정 예시 4개 (few-shot)
    m2    m0 + Critical 체크리스트 (첫 응답 뒤 예/아니오 질문 6개, 코드가 Critical 여부 결정)
    m1m2  둘 다 (m1·m2가 모두 채택 대상일 때만 측정)

[설계 의도]
1. 예시 원문은 검토자가 승인한 문서(docs/method/m1_examples.md)에서 실행할 때 읽는다. 코드에 같은 문장을
   따로 적어 두면 문서와 코드 중 한쪽만 고쳐질 수 있다. 문서의 [입력]·[출력] 블록 4쌍을 그대로 쓴다.
   줄바꿈은 LF로 맞춘다. Windows에서 git이 CRLF로 체크아웃하면 같은 문서라도 프롬프트 문자열과 지문이 달라지기 때문이다.
2. 예시 블록 앞에 "예시의 기기·수치·상황을 응답에 옮겨 쓰지 말 것"을 한 줄 둔다. 예시 내용을 옮겨 쓰면
   입력에 없는 사실이 되어 날조로 판정된다(계획 §4 "예시 내용 복사"). 옮겨 쓰는 경우가 생기면 그대로 측정한다.
3. 체크리스트 질문 문구는 계획 §2.2의 6문항 그대로다. 6번은 서버 장애와 민감 텍스트를 함께 묻되, 답을
   "서버 장애 / 민감한 텍스트 / 아니오" 중 하나로 받아 코드가 둘을 구분한다. 재현 정보가 부족할 때
   서버 장애만 예외로 올리는 규칙(기준서 H-3a·H-1b)을 적용하려면 이 구분이 필요하다.
4. 체크리스트는 Critical로 올리기만 한다(decide_upgrade). 첫 응답이 Critical이면 답을 기록만 하고 바꾸지 않는다.
   [우선순위] 줄만 바꾸고 다른 필드는 그대로 둔다. 바뀐 우선순위는 후처리 안전장치 H-1이 긴급 사인 요청으로 보낸다.
5. 판단 필드(분류·우선순위·재현 정보)가 허용 값 밖이면 체크리스트로 바꾸지 않는다. 허용 값 밖인 값을
   Critical로 덮으면 형식 위반(R6)이 가려진다(guardrail.py 설계 의도 4와 같은 원칙).
"""

import hashlib
import re

from triage_eval.common.paths import ROOT
from triage_eval.pipeline.contract import ENUMS_V2, parse_v2, replace_field

EXAMPLES_DOC = ROOT / "docs" / "method" / "m1_examples.md"
METHODS = {"m0": (False, False), "m1": (True, False), "m2": (False, True), "m1m2": (True, True)}  # (예시, 체크리스트)

_BLOCK = re.compile(r"\*\*\[입력\]\*\*\s*```text\n(.*?)```\s*\*\*\[출력\]\*\*\s*```text\n(.*?)```", re.S)


def load_examples(path=EXAMPLES_DOC) -> list[tuple[str, str]]:
    """설계 의도 1 — 문서의 (입력, 출력) 쌍. 형식이 예상과 다르면 실행하지 않도록 예외를 낸다."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")  # Windows 체크아웃(CRLF)에서도 같은 문자열
    pairs = [(a.strip(), b.strip()) for a, b in _BLOCK.findall(text)]
    if len(pairs) != 4:
        raise ValueError(f"판정 예시는 4개여야 합니다 (문서에서 {len(pairs)}개를 읽음): {path}")
    return pairs


def examples_block(pairs: list[tuple[str, str]] | None = None) -> str:
    """시스템 프롬프트와 [리포트] 사이에 넣는 예시 블록 (설계 의도 2)."""
    pairs = load_examples() if pairs is None else pairs
    lines = ["", "판정 예시 (규칙을 적용한 예시입니다. 예시의 기기·수치·상황을 응답에 옮겨 쓰지 마세요.)"]
    for n, (inp, out) in enumerate(pairs, start=1):
        lines += ["", f"[예시 {n} 리포트]", inp, f"[예시 {n} 응답]", out]
    lines.append("")
    return "\n".join(lines)


YES, NO = "예", "아니오"
Q6_CHOICES = ["서버 장애", "민감한 텍스트", NO]
CHECKLIST = [
    "이 현상 때문에 게임 실행·로그인·메인 진행을 할 수 없고, 우회 방법이 없는가?",
    "결제 후 미지급·이중 결제처럼 유료 결제에 피해가 있는가?",
    "캐릭터·아이템·재화 데이터가 사라지거나 이전 상태로 되돌아갔는가?",
    "재화·보상·입장 기회를 반복해서 얻는 악용이 가능하거나, 승패·랭킹 기록이 남지 않는가?",
    "공지된 조정 내용과 실제 수치가 크게 다른가?",
    "여러 유저가 동시에 겪는 서버 장애로 보이는가, 또는 분쟁 지역 명칭·필터를 우회한 욕설처럼 민감한 텍스트 오류인가?",
]
CHECKLIST_KEYS = [f"q{i}" for i in range(1, 7)]
CHECKLIST_SCHEMA = {
    "type": "object",
    "properties": {**{k: {"type": "string", "enum": [YES, NO]} for k in CHECKLIST_KEYS[:5]},
                   "q6": {"type": "string", "enum": Q6_CHOICES}},
    "required": CHECKLIST_KEYS,
}
CHECKLIST_POLICY = {"asked_when": "분류=결함", "rule": "upgrade_only", "num_predict": 96}


def checklist_text() -> str:
    lines = ["", "[Critical 확인 질문]",
             "위 리포트와 1차 판정을 보고, 리포트에 적힌 내용만으로 답하세요. 확실하지 않으면 아니오입니다."]
    lines += [f"{n}. {q}" for n, q in enumerate(CHECKLIST, start=1)]
    lines.append("JSON으로 답하세요. 키는 q1~q6입니다. q1~q5의 값은 예 또는 아니오, "
                 "q6의 값은 서버 장애, 민감한 텍스트, 아니오 중 하나입니다.")
    return "\n".join(lines)


def build_checklist_prompt(base_prompt: str, first_response: str) -> str:
    return f"{base_prompt}\n\n[1차 판정]\n{first_response.strip()}\n{checklist_text()}"


def should_ask(pred: dict) -> bool:
    return pred.get("분류") == "결함"


def decide_upgrade(pred: dict, answers: dict) -> tuple[bool, str]:
    """설계 의도 4·5 — (올릴지, 사유). answers 는 q1~q6 값."""
    if any(pred.get(f) not in ENUMS_V2[f] for f in ("분류", "우선순위", "재현 정보")):
        return False, "판단 필드 허용 값 밖 — 변경 안 함"
    if pred["우선순위"] == "Critical":
        return False, "이미 Critical — 기록만"
    if not answers or any(k not in answers for k in CHECKLIST_KEYS):
        return False, "체크리스트 답 없음"
    server = answers["q6"] == "서버 장애"
    any_yes = any(answers[k] == YES for k in CHECKLIST_KEYS[:5]) or answers["q6"] != NO
    if pred["재현 정보"] == "부족":
        return (True, "재현 정보 부족이지만 서버 장애 의심 (H-1b)") if server else (False, "재현 정보 부족 (H-3a)")
    return (True, "체크리스트 '예' — Critical") if any_yes else (False, "체크리스트 모두 아니오")


def apply_upgrade(text: str) -> str:
    return replace_field(text, "우선순위", "Critical")


def assets_sha256(method: str) -> str | None:
    """실행 기록에 남길 방법 구성의 지문. 예시 문서나 질문 문구가 바뀌면 달라진다."""
    use_ex, use_cl = METHODS[method]
    if not (use_ex or use_cl):
        return None
    parts = [examples_block() if use_ex else "", checklist_text() if use_cl else "", repr(CHECKLIST_SCHEMA) if use_cl else ""]
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


__all__ = ["METHODS", "load_examples", "examples_block", "CHECKLIST", "CHECKLIST_SCHEMA", "CHECKLIST_POLICY",
           "build_checklist_prompt", "should_ask", "decide_upgrade", "apply_upgrade", "assets_sha256", "parse_v2"]
