"""출력 형식 v2 (v1.3 평가셋용) — 필드 정의, 파싱, 형식 채점.

v1.0의 5필드 형식(score_format.py)은 v1.0 10문항과 README 수치의 출처이므로 그대로 두고,
v1.3 판정 체계(docs/dataset/triage_guideline.md)에 맞춘 8필드 형식을 이 파일에 따로 정의한다.

필드 (순서 고정)
----------------
    [요약] [분류] [모듈] [우선순위] [재현 정보] [발생 빈도] [처리] [누락 정보 및 권장 조치]

형식 규칙 (v1의 R1~R6과 같은 뜻, 대상 필드만 v2 기준)
------------------------------------------------------
    R1 no_preamble      응답이 '[요약]'으로 시작
    R2 all_fields       8개 필드가 모두 있음
    R3 field_order      필드 순서가 규격과 같음
    R4 no_blank_line    빈 줄 없음
    R5 no_stray_text    마지막 필드 앞에 필드가 아닌 줄이 없음
    R6 enum_valid       선택지 필드 5개와 [모듈]의 값이 허용 값 안에 있음

[설계 의도]
1. 줄 파서(parse_lines)는 score_format.py 것을 그대로 쓴다. "필드 한 줄"의 정의가 두 곳에 있으면
   v1과 v2 채점이 서로 다른 기준으로 갈라진다.
2. 허용 값은 tools/dataset_v13/merge_dataset.py 의 ENUMS(정답 라벨 검증용)와 같아야 한다.
   tests/test_contract_v2.py 가 두 정의의 일치를 확인한다.
3. 값 비교 전에 앞뒤 공백, 끝의 마침표, 감싼 따옴표·백틱만 정리한다. 그 이상(동의어 매핑 등)은 하지 않는다.
   "Major급" 같은 값을 Major로 고쳐 주면 형식 위반이 점수에서 사라져, 파서가 실제 운영에서
   읽지 못할 응답을 정상으로 오판하게 된다.
4. [모듈]은 복합 이슈일 때 "/"로 병기할 수 있다. "·"는 모듈 이름 안에 들어 있으므로(계정·로그인) 구분자로 쓰지 않는다.
"""

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

RULES_V2 = {
    "R1_no_preamble": "응답이 '[요약]'으로 즉시 시작 (서두 사족 없음)",
    "R2_all_fields": "8개 필드 라벨 전부 존재",
    "R3_field_order": "필드 순서가 규격과 일치",
    "R4_no_blank_line": "필드 사이 빈 줄 없음",
    "R5_no_stray_text": "필드 라벨이 아닌 줄이 중간에 끼어들지 않음",
    "R6_enum_valid": "선택지 필드 5개와 [모듈] 값이 허용 값에 포함",
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


def score_format_v2(text: str) -> dict:
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

    bad = [f"{f}={values.get(f)!r}" for f, allowed in ENUMS_V2.items() if values.get(f) not in allowed]
    mods = split_modules(values.get("모듈", ""))
    if not mods or any(m not in MODULES + [NO_MODULE] for m in mods) or (NO_MODULE in mods and len(mods) > 1):
        bad.append(f"모듈={values.get('모듈')!r}")
    results["R6_enum_valid"] = not bad
    if bad:
        reasons["R6_enum_valid"] = ", ".join(bad)

    return {
        "rules": results,
        "failed_rules": [k for k, v in results.items() if not v],
        "reasons": reasons,
        "strict_pass": all(results.values()),
        "parsable_pass": all(v for k, v in results.items() if k != "R4_no_blank_line"),
    }
