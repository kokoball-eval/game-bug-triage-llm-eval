"""출력 형식 v2 (contract_v2.py) 테스트."""

import sys
from pathlib import Path

from contract_v2 import ENUMS_V2, FIELDS_V2, MODULES, parse_v2, score_format_v2, split_modules

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "dataset_v13"))
import merge_dataset  # noqa: E402

GOOD = "\n".join([
    "[요약]: 패키지 결제 후 다이아 미지급",
    "[분류]: 결함",
    "[모듈]: 결제·재화",
    "[우선순위]: Critical",
    "[재현 정보]: 충분",
    "[발생 빈도]: 1회",
    "[처리]: 긴급 사인 요청",
    "[누락 정보 및 권장 조치]: 결제 로그 확인",
])


def test_enums_match_dataset_validator():
    """출력 형식의 허용 값과 정답 라벨 검증의 허용 값은 같아야 한다 (설계 의도 2)."""
    for field, values in ENUMS_V2.items():
        assert values == merge_dataset.ENUMS[field]
    assert MODULES == merge_dataset.ENUMS["모듈"]


def test_good_response_passes_all_rules():
    s = score_format_v2(GOOD)
    assert s["strict_pass"] and s["failed_rules"] == []
    assert parse_v2(GOOD)["처리"] == "긴급 사인 요청"


def test_preamble_and_old_enum_fail():
    s = score_format_v2("분석 결과입니다.\n" + GOOD.replace("긴급 사인 요청", "즉시 전달"))
    assert "R1_no_preamble" in s["failed_rules"] and "R6_enum_valid" in s["failed_rules"]


def test_missing_field_fails_r2():
    s = score_format_v2("\n".join(l for l in GOOD.split("\n") if not l.startswith("[발생 빈도]")))
    assert "R2_all_fields" in s["failed_rules"]


def test_blank_line_is_parsable_but_not_strict():
    s = score_format_v2(GOOD.replace("\n[처리]", "\n\n[처리]"))
    assert not s["strict_pass"] and s["parsable_pass"]


def test_value_noise_is_cleaned_but_synonyms_are_not():
    assert parse_v2(GOOD.replace(": Critical", ": Critical."))["우선순위"] == "Critical"
    s = score_format_v2(GOOD.replace(": Critical", ": Critical급"))
    assert "R6_enum_valid" in s["failed_rules"]


def test_module_split_keeps_middle_dot():
    assert split_modules("계정·로그인 / 결제·재화") == ["계정·로그인", "결제·재화"]
    assert "R6_enum_valid" in score_format_v2(GOOD.replace("결제·재화", "해당 없음 / 결제·재화"))["failed_rules"]


def test_field_order_constant():
    assert FIELDS_V2[0] == "요약" and FIELDS_V2[-1] == "누락 정보 및 권장 조치" and len(FIELDS_V2) == 8


def test_r7_flags_language_drift_but_allows_english_terms():
    """응답 도중 중국어로 넘어가면 위반, 선택지 값(Critical)·용어(PvP)의 영문은 허용 (설계 의도 5)."""
    assert "R7_output_language" not in score_format_v2(GOOD.replace("결제 로그 확인", "PvP 결투장 SSR 로그 확인"))["failed_rules"]
    drift = score_format_v2(GOOD.replace("패키지 결제 후 다이아 미지급", "업데이트 이후 폰 과热无法翻译"))
    assert "R7_output_language" in drift["failed_rules"] and not drift["strict_pass"] and not drift["parsable_pass"]


def test_r7_target_language_is_configurable():
    """글로벌 BTS(en)라면 한글이 위반이 된다 — 규칙은 그대로, 설정값만 바뀐다."""
    english = GOOD.replace("패키지 결제 후 다이아 미지급", "Diamonds not granted after purchase")
    assert "R7_output_language" in score_format_v2(GOOD, lang="en")["failed_rules"]
    assert "R7_output_language" not in score_format_v2(english, lang="ko")["failed_rules"]


def test_prompt_states_output_language():
    from prompt_v2 import SYSTEM_PROMPT_V2
    assert "모든 필드는 한국어로 작성하세요" in SYSTEM_PROMPT_V2 and "{output_language}" not in SYSTEM_PROMPT_V2


def test_language_errors_point_to_free_text_field():
    from contract_v2 import language_errors
    vals = {"요약": "폰이 10분만에 과熱", "누락 정보 및 권장 조치": "기기 정보", "분류": "결함"}
    assert language_errors(vals) == [("요약", "熱")]
    assert language_errors({"요약": "Critical 크래시 SSR"}) == []


def test_r7_allowlist_catches_any_foreign_script():
    """허용 목록 방식 — 한자·가나·키릴뿐 아니라 그 밖의 문자 체계와 전각 구두점·이모지도 잡는다."""
    from contract_v2 import FORBIDDEN_SCRIPTS
    ko = FORBIDDEN_SCRIPTS["ko"]
    for foreign in ("過熱", "ログイン", "ошибка", "เกม", "لعبة", "λάθος", "lỗi", "，", "：", "\uf900", "\U00020000", "😀"):
        assert ko.search(foreign), foreign
    for allowed in ("계정·로그인", "Critical 크래시 SSR PvP", "→ ↔ ① ★ ■ — … “인용”", "10% 3회 ×2 30°C", "ㄱㄴ"):
        assert not ko.search(allowed), allowed


def test_r7_allowlist_has_no_false_positive_on_inputs():
    """평가셋 입력 원문에 쓰인 문자는 모두 허용 목록 안에 있다 (모델이 입력을 인용해도 오탐하지 않는다)."""
    import json
    from pathlib import Path
    from contract_v2 import FORBIDDEN_SCRIPTS
    data = json.loads((Path(__file__).resolve().parent.parent / "data/eval_v13/aether_raid_v13.json").read_text(encoding="utf-8"))
    for item in data["items"]:
        assert not FORBIDDEN_SCRIPTS["ko"].search(json.dumps(item["input"], ensure_ascii=False)), item["id"]
