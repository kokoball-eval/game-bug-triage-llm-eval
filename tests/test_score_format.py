"""score_format.py 채점 규칙(R1~R6) 단위 테스트.

규칙마다 "그 규칙 하나만 어기는 응답"을 만들어, 정확히 그 규칙만 실패하는지 확인한다.
여러 규칙이 한꺼번에 실패하는 응답으로 테스트하면, 한 규칙이 고장 나도 다른 규칙이
대신 실패해 주는 바람에 테스트가 통과해 버린다.
"""

import pytest

from triage_eval.common.score_format import score_response

# 5개 필드를 규격대로 모두 지킨 응답 (모든 테스트의 출발점)
GOOD = "\n".join([
    "[요약]: 보스 3단계 진입 시 앱 강제 종료",
    "[모듈]: 전투",
    "[심각도]: Blocker",
    "[재현 여부]: 발생(100%)",
    "[누락 정보 및 권장 조치]: 기기 모델명 확인 필요",
])


def test_good_response_passes_every_rule():
    result = score_response(GOOD)
    assert result["failed_rules"] == []
    assert result["strict_pass"] is True
    assert result["parsable_pass"] is True


@pytest.mark.parametrize("text, expected_rule", [
    # R1: 서두 사족
    ("분석 결과는 다음과 같습니다.\n" + GOOD, "R1_no_preamble"),
    # R2: 필드 누락 (마지막 필드 삭제)
    ("\n".join(GOOD.split("\n")[:4]), "R2_all_fields"),
    # R6: 심각도 enum 이탈
    (GOOD.replace("Blocker", "매우 심각"), "R6_enum_valid"),
    # R6: 재현 여부 enum 이탈
    (GOOD.replace("발생(100%)", "항상 발생"), "R6_enum_valid"),
])
def test_single_rule_violation_fails_only_that_rule(text, expected_rule):
    result = score_response(text)
    assert expected_rule in result["failed_rules"]
    assert result["strict_pass"] is False


def test_field_order_swap_fails_r3():
    lines = GOOD.split("\n")
    lines[1], lines[2] = lines[2], lines[1]      # [모듈] ↔ [심각도]
    result = score_response("\n".join(lines))
    assert result["failed_rules"] == ["R3_field_order"]


def test_stray_text_between_fields_fails_r5():
    lines = GOOD.split("\n")
    lines.insert(2, "참고: 보스 패턴 관련 이슈로 보입니다")
    result = score_response("\n".join(lines))
    assert result["failed_rules"] == ["R5_no_stray_text"]


def test_blank_line_fails_strict_but_stays_parsable():
    """R4(빈 줄)는 STRICT 에서만 실패로 치고 PARSABLE 에서는 허용한다 — v1.0 Llama 실패의 전부."""
    result = score_response(GOOD.replace("\n", "\n\n"))
    assert result["failed_rules"] == ["R4_no_blank_line"]
    assert result["strict_pass"] is False
    assert result["parsable_pass"] is True


@pytest.mark.parametrize("value", ["발생(100%)", "간헐적", "불명확", "재현 불가"])
def test_every_allowed_reproducibility_value_is_accepted(value):
    result = score_response(GOOD.replace("발생(100%)", value))
    assert "R6_enum_valid" not in result["failed_rules"]


@pytest.mark.parametrize("text", ["", None, "   \n  "])
def test_empty_response_fails_without_crashing(text):
    """호출 실패 회차는 response_text 가 빈 문자열이다. 채점기가 죽지 않고 실패로 처리해야 한다."""
    result = score_response(text)
    assert result["strict_pass"] is False
    assert result["parsable_pass"] is False


def test_v1_0_log_reproduces_readme_numbers(baseline):
    """회귀 방지: 실제 v1.0 로그를 채점하면 README 표의 수치가 그대로 나와야 한다.

    채점 규칙을 고쳤는데 이 테스트가 깨지면, 문서의 포맷 준수율이 더는 재현되지 않는다는 뜻이다.
    """
    def rates(model):
        rows = [r for r in baseline["results"] if r["model"] == model]
        scored = [score_response(r["response_text"]) for r in rows]
        return (len(rows),
                sum(s["strict_pass"] for s in scored),
                sum(s["parsable_pass"] for s in scored))

    assert rates("qwen2.5:7b") == (20, 20, 20)   # STRICT 100% / PARSABLE 100%
    assert rates("llama3.1:8b") == (20, 1, 20)   # STRICT 5%   / PARSABLE 100%
