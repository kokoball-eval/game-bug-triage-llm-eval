"""출력 형식 v2 (v1.3 평가셋용) — 필드 정의, 파싱, 형식 채점.

v1.0의 5필드 형식(score_format.py)은 v1.0 10문항과 README 수치의 출처이므로 그대로 두고,
v1.3 판정 체계(docs/dataset/triage_guideline.md)에 맞춘 8필드 형식을 이 파일에 따로 정의한다.

필드 (순서 고정)
----------------
    [요약] [분류] [모듈] [우선순위] [재현 정보] [발생 빈도] [처리] [누락 정보 및 권장 조치]

형식 규칙 (R1~R6은 v1과 같은 뜻, 대상 필드만 v2 기준 / R7은 v1.3에서 추가)
------------------------------------------------------
    R1 no_preamble      응답이 '[요약]'으로 시작
    R2 all_fields       8개 필드가 모두 있음
    R3 field_order      필드 순서가 규격과 같음
    R4 no_blank_line    빈 줄 없음
    R5 no_stray_text    마지막 필드 앞에 필드가 아닌 줄이 없음
    R6 enum_valid       선택지 필드 5개와 [모듈]의 값이 허용 값 안에 있음
    R7 output_language  응답이 지정된 출력 언어(OUTPUT_LANG)로 쓰였음 — 다른 문자 체계가 섞이지 않음

[설계 의도]
1. 줄 파서(parse_lines)는 score_format.py 것을 그대로 쓴다. "필드 한 줄"의 정의가 두 곳에 있으면
   v1과 v2 채점이 서로 다른 기준으로 갈라진다.
2. 허용 값은 tools/dataset_v13/merge_dataset.py 의 ENUMS(정답 라벨 검증용)와 같아야 한다.
   tests/test_contract_v2.py 가 두 정의의 일치를 확인한다.
3. 값 비교 전에 앞뒤 공백, 끝의 마침표, 감싼 따옴표·백틱만 정리한다. 그 이상(동의어 매핑 등)은 하지 않는다.
   "Major급" 같은 값을 Major로 고쳐 주면 형식 위반이 점수에서 사라져, 파서가 실제 운영에서
   읽지 못할 응답을 정상으로 오판하게 된다.
4. [모듈]은 복합 이슈일 때 "/"로 병기할 수 있다. "·"는 모듈 이름 안에 들어 있으므로(계정·로그인) 구분자로 쓰지 않는다.
5. (R7) 출력 언어는 입력 언어와 별개로 "BTS를 쓰는 팀이 읽는 언어"로 고정한다. 프롬프트 v2.1 측정에서
   Qwen이 한국어 입력에 대해 응답 도중 중국어로 넘어가는 실패가 나왔다(docs/issue_log.md ISSUE-007).
   판정은 문자 체계로 하며, 금지 목록이 아니라 허용 목록을 쓴다. ko 기준으로 한글, ASCII(영문·숫자·기호 —
   선택지 값 Critical·Major, 용어 SSR·PvP 등), 일반 구두점·화살표·원문자 등 일부 기호만 허용하고 나머지는 모두 위반이다.
   처음에는 한자·가나·키릴만 금지했으나, 그 방식으로는 태국어·아랍어·그리스어, 전각 구두점(，：。), 호환 한자,
   이모지 등이 빠진다. 허용 목록으로 바꾼 뒤 지금까지의 모든 실행 기록과 평가셋 입력 63건을 다시 검사해,
   기존에 잡힌 위반은 그대로 잡히고 새 오탐은 없음을 확인했다.
   한계: 문자 체계로 판정하므로 악센트 없는 라틴 문자로 쓴 외국어 문장(예: 영어·스페인어 문장)은 잡지 못한다.
   영문 용어를 허용해야 하므로 라틴 문자 자체는 막을 수 없다. 언어 식별이 필요하면 별도 판정기를 둔다(로드맵).
   글로벌 BTS라면 OUTPUT_LANG 을 en 으로 바꾸고, 그때는 한글을 포함해 ASCII·기호 밖의 문자가 모두 위반이 된다.
"""

import re

from score_format import parse_lines

FIELDS_V2 = ["요약", "분류", "모듈", "우선순위", "재현 정보", "발생 빈도", "처리", "누락 정보 및 권장 조치"]

ENUMS_V2 = {
    "분류": ["결함", "개선 제안", "버그 아님", "문의·건의", "중복 의심", "무관"],
    "우선순위": ["Critical", "Major", "Minor", "Trivial", "판단보류", "해당 없음"],
    "재현 정보": ["충분", "부족"],
    "발생 빈도": ["항상", "간헐적", "1회", "미기재", "해당 없음"],
    "처리": ["긴급 사인 요청", "등록(재현 대기)", "개발 배정", "정보 요청 후 보류", "CS 응대", "폐기"],
}
MODULES = ["클라이언트 안정성", "네트워크", "계정·로그인", "결제·재화", "콘텐츠 진행",
           "게임플레이·밸런스", "그래픽·사운드", "UI·텍스트", "플랫폼 호환성", "보안·어뷰징"]
NO_MODULE = "해당 없음"

# 출력 언어 (R7, 설계 의도 5) — BTS를 쓰는 팀이 읽는 언어. 입력 언어와 무관하다.
OUTPUT_LANG = "ko"
LANG_NAMES = {"ko": "한국어", "en": "영어"}
# 허용 목록 방식 (설계 의도 5) — 출력 언어에서 쓰는 문자만 나열하고, 그 밖의 문자는 모두 위반으로 본다.
_COMMON = (r"\x09\x0a\x0d\x20-\x7e"        # ASCII (영문·숫자·기호 — 선택지 값 Critical, 용어 SSR·PvP 등)
           r"\u00b7\u00d7\u00b0\u2103"      # · × ° ℃
           r"\u2010-\u205e"                  # 일반 구두점 (— … “ ” ‘ ’)
           r"\u2190-\u21ff"                  # 화살표 (→ ↔)
           r"\u2460-\u24ff\u25a0-\u25ff\u2600-\u26ff")  # ① ■ ★ 등 기호
_HANGUL = r"\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f"
FORBIDDEN_SCRIPTS = {
    "ko": re.compile(f"[^{_COMMON}{_HANGUL}]"),
    "en": re.compile(f"[^{_COMMON}]"),
}

# 한 줄 자유 서술 값의 허용 문자 패턴 (JSON 스키마 pattern 용, run_eval_v2 설계 의도 6).
# 위 허용 목록에서 줄바꿈·탭과 JSON 문자열을 깨뜨리는 큰따옴표(")·역슬래시(\)를 뺀 것이다.
# 문법 변환기가 \u 이스케이프를 읽지 못할 수 있어 실제 문자로 쓴다.
_LINE_ASCII = " !#-\\[\\]-~"                       # 0x20, 0x21, 0x23-0x5B, 0x5D-0x7E (" 와 \ 제외)
_LINE_EXTRA = ("\u00b7\u00d7\u00b0\u2103\u2010-\u205e\u2190-\u21ff"
               "\u2460-\u24ff\u25a0-\u25ff\u2600-\u26ff")   # · × ° ℃, 구두점·화살표·원문자 등 (실제 문자로 해석됨)
_LINE_HANGUL = "\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f"
LINE_PATTERNS = {
    "ko": f"^[{_LINE_ASCII}{_LINE_EXTRA}{_LINE_HANGUL}]+$",
    "en": f"^[{_LINE_ASCII}{_LINE_EXTRA}]+$",
}

RULES_V2 = {
    "R1_no_preamble": "응답이 '[요약]'으로 즉시 시작 (서두 사족 없음)",
    "R2_all_fields": "8개 필드 라벨 전부 존재",
    "R3_field_order": "필드 순서가 규격과 일치",
    "R4_no_blank_line": "필드 사이 빈 줄 없음",
    "R5_no_stray_text": "필드 라벨이 아닌 줄이 중간에 끼어들지 않음",
    "R6_enum_valid": "선택지 필드 5개와 [모듈] 값이 허용 값에 포함",
    "R7_output_language": "응답이 지정된 출력 언어로 작성됨 (다른 문자 체계가 섞이지 않음)",
}


def clean(value: str) -> str:
    """설계 의도 3 — 표기 잡음만 정리한다."""
    v = (value or "").strip().strip("`'\"").strip()
    return v[:-1].strip() if v.endswith(".") else v


def split_modules(value: str) -> list[str]:
    """설계 의도 4 — '/' 와 ',' 로만 나눈다."""
    parts = [clean(p) for p in clean(value).replace(",", "/").split("/")]
    return [p for p in parts if p]


def parse_v2(text: str) -> dict:
    """응답에서 8개 필드 값을 꺼낸다. 같은 필드가 여러 번 나오면 첫 값을 쓴다."""
    values = {}
    for label, value, _ in parse_lines((text or "").strip()):
        if label in FIELDS_V2 and label not in values:
            values[label] = clean(value) if label != "모듈" else value.strip()
    return values


def enum_errors(values: dict) -> list[tuple[str, str | None]]:
    """R6 판정의 단일 정의 — 허용 값 밖인 (필드, 값) 목록. 형식 채점과 재요청 안내문(prompt_v2)이 함께 쓴다."""
    bad = [(f, values.get(f)) for f, allowed in ENUMS_V2.items() if values.get(f) not in allowed]
    mods = split_modules(values.get("모듈", ""))
    if not mods or any(m not in MODULES + [NO_MODULE] for m in mods) or (NO_MODULE in mods and len(mods) > 1):
        bad.append(("모듈", values.get("모듈")))
    return bad


FREE_TEXT_FIELDS = ["요약", "누락 정보 및 권장 조치"]  # 선택지가 없는 필드. 다른 문자 체계는 여기에서만 생길 수 있다


def language_errors(values: dict, lang: str = OUTPUT_LANG) -> list[tuple[str, str]]:
    """R7 위반 위치 — 출력 언어 밖 문자가 섞인 자유 서술 필드 (필드, 섞인 문자) 목록.
    선택지 필드에 섞인 경우는 허용 값 위반(R6)으로 잡히므로 여기서는 보지 않는다."""
    out = []
    for f in FREE_TEXT_FIELDS:
        found = FORBIDDEN_SCRIPTS[lang].findall(values.get(f) or "")
        if found:
            out.append((f, "".join(dict.fromkeys(found))))
    return out


def replace_field(text: str, field: str, value: str) -> str:
    """필드 한 줄의 값만 바꾼다. 다른 줄과 빈 줄은 그대로 둔다. 필드 줄이 없으면 원문을 돌려준다."""
    pattern = re.compile(rf"^(\s*\[{re.escape(field)}\]\s*[:：]).*$", re.M)
    return pattern.sub(lambda m: f"{m.group(1)} {value}", text, count=1)


def score_format_v2(text: str, lang: str = OUTPUT_LANG) -> dict:
    text = (text or "").strip()
    parsed = parse_lines(text)
    labels = [lbl for lbl, _, _ in parsed if lbl not in ("__BLANK__", "__TEXT__")]
    values = parse_v2(text)
    results, reasons = {}, {}

    results["R1_no_preamble"] = text.startswith("[요약]")
    if not results["R1_no_preamble"]:
        reasons["R1_no_preamble"] = f"첫 40자: {text[:40]!r}"

    missing = [f for f in FIELDS_V2 if f not in labels]
    results["R2_all_fields"] = not missing
    if missing:
        reasons["R2_all_fields"] = f"누락 필드: {missing}"

    spec = [lbl for lbl in labels if lbl in FIELDS_V2]
    results["R3_field_order"] = spec == FIELDS_V2
    if not results["R3_field_order"]:
        reasons["R3_field_order"] = f"실제 순서: {spec}"

    blanks = [idx for lbl, _, idx in parsed if lbl == "__BLANK__"]
    results["R4_no_blank_line"] = not blanks
    if blanks:
        reasons["R4_no_blank_line"] = f"빈 줄 {len(blanks)}개"

    last = next((pos for pos, (lbl, _, _) in enumerate(parsed) if lbl == FIELDS_V2[-1]), None)
    stray = [val for pos, (lbl, val, _) in enumerate(parsed) if lbl == "__TEXT__" and (last is None or pos < last)]
    results["R5_no_stray_text"] = not stray
    if stray:
        reasons["R5_no_stray_text"] = f"비규격 줄 {len(stray)}개: {[s[:30] for s in stray]}"

    bad = [f"{f}={v!r}" for f, v in enum_errors(values)]
    results["R6_enum_valid"] = not bad
    if bad:
        reasons["R6_enum_valid"] = ", ".join(bad)

    foreign = FORBIDDEN_SCRIPTS[lang].findall(text)
    results["R7_output_language"] = not foreign
    if foreign:
        reasons["R7_output_language"] = f"{LANG_NAMES[lang]} 외 문자 {len(foreign)}자: {''.join(foreign[:10])!r}"

    return {
        "rules": results,
        "failed_rules": [k for k, v in results.items() if not v],
        "reasons": reasons,
        "strict_pass": all(results.values()),
        "parsable_pass": all(v for k, v in results.items() if k != "R4_no_blank_line"),
    }
