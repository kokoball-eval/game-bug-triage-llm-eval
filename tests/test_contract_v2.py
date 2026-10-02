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
