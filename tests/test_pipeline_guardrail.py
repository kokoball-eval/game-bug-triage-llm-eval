"""guardrail.py 테스트 — 규칙 동작, 라벨 미사용, 원본 보존, 형식 위반 비보정, H-0 안전 규칙."""

import copy
import json
from pathlib import Path

from triage_eval.pipeline.contract import parse_v2, score_format_v2
from triage_eval.pipeline.guardrail import GUARDRAIL_VERSION, apply, apply_record

ROOT = Path(__file__).resolve().parent.parent
DATA = {i["id"]: i for i in json.loads((ROOT / "data/eval_v13/aether_raid_v13.json").read_text(encoding="utf-8"))["items"]}


def resp(cls="결함", pri="Major", rep="충분", act="등록(재현 대기)", blank=False):
    lines = ["[요약]: 보스전 진입 시 튕김", f"[분류]: {cls}", "[모듈]: 클라이언트 안정성", f"[우선순위]: {pri}",
             f"[재현 정보]: {rep}", "[발생 빈도]: 항상", f"[처리]: {act}", "[누락 정보 및 권장 조치]: 로그 확인"]
    if blank:
        lines.insert(4, "")
    return "\n".join(lines)


def action(text):
    return parse_v2(text)["처리"]


def test_h1_critical_goes_to_sign_off():
    out, applied = apply(resp(pri="Critical", act="등록(재현 대기)"), "A")
    assert action(out) == "긴급 사인 요청" and applied[0]["rule"] == "H-1"


def test_h1_excludes_duplicate():
    out, applied = apply(resp(cls="중복 의심", pri="Critical", act="폐기"), "A")
    assert action(out) == "폐기" and not applied


def test_h2_track_a_defect_not_assigned_to_dev():
    out, applied = apply(resp(act="개발 배정"), "A")
    assert action(out) == "등록(재현 대기)" and applied[0]["rule"] == "H-2"
    out, _ = apply(resp(rep="부족", act="개발 배정"), "A")
    assert action(out) == "정보 요청 후 보류"


def test_h2_keeps_improvement_proposal_assignment():
    """개선 제안은 입력 종류와 관계없이 개발 배정이다."""
    out, applied = apply(resp(cls="개선 제안", pri="Minor", act="개발 배정"), "A")
    assert action(out) == "개발 배정" and not applied


def test_h2b_qa_reported_defect_goes_to_dev():
    out, applied = apply(resp(), "B", "내부 QA")
    assert action(out) == "개발 배정" and applied[0]["rule"] == "H-2b"
    assert apply(resp(), "B", "운영/CS")[1] == []          # 운영/CS 작성 건은 재현 대기가 맞다
    assert apply(resp(rep="부족"), "B", "내부 QA")[1] == []  # 재현 정보가 부족하면 손대지 않는다


def test_only_action_line_changes():
    """설계 의도 3 — [처리] 줄 외에는 글자 하나 바뀌지 않는다."""
    src = resp(pri="Critical")
    out, _ = apply(src, "A")
    diff = [(a, b) for a, b in zip(src.split("\n"), out.split("\n")) if a != b]
    assert len(diff) == 1 and diff[0][0].startswith("[처리]")


def test_format_violations_are_not_fixed():
    """설계 의도 4 — 허용 값 밖이면 보정하지 않아 R6 위반이 그대로 남는다."""
    bad = resp(pri="Critical급")
    assert apply(bad, "A") == (bad, [])
    bad2 = resp(pri="Critical", act="긴급 처리")
    assert apply(bad2, "A") == (bad2, [])
    assert not score_format_v2(bad2)["rules"]["R6_enum_valid"]


def test_blank_line_is_kept():
    out, _ = apply(resp(pri="Critical", blank=True), "A")
    assert not score_format_v2(out)["rules"]["R4_no_blank_line"]


def test_labels_are_not_used():
    """설계 의도 1 — 정답 라벨을 바꿔도 보정 결과가 같다."""
    item = DATA["A01"]
    rec = {"success": True, "response_text": resp(pri="Critical")}
    tampered = copy.deepcopy(item)
    tampered["labels"] = {k: ["엉뚱한 값"] for k in item["labels"]}
    assert apply_record(rec, item) == apply_record(rec, tampered)


def test_record_keeps_raw_response():
    rec = {"success": True, "response_text": resp(pri="Critical")}
    out = apply_record(rec, DATA["A01"])
    assert out["raw_response_text"] == rec["response_text"]
    assert action(out["response_text"]) == "긴급 사인 요청"
    assert out["guardrail"]["version"] == GUARDRAIL_VERSION and out["guardrail"]["applied"]


def test_failed_call_is_untouched():
    out = apply_record({"success": False, "response_text": ""}, DATA["A01"])
    assert out["response_text"] == "" and out["guardrail"]["applied"] == []


def test_h0_unreadable_judgment_is_not_closed():
    """H-0 — 판단 필드가 허용 값 밖이면 폐기·CS 응대·개발 배정으로 끝내지 않는다 (v2.3 A10 사례)."""
    for act in ("폐기", "CS 응대", "개발 배정"):
        out, applied = apply(resp(cls="무관 중", pri="해당 없음", rep="부족", act=act), "A")
        assert action(out) == "정보 요청 후 보류" and applied[0]["rule"] == "H-0"


def test_h0_keeps_invalid_value_and_r6_violation():
    """H-0은 [처리]만 바꾼다. 허용 값 밖인 값은 남아 R6 위반으로 계속 집계된다."""
    out, _ = apply(resp(cls="무관 중", act="폐기"), "A")
    assert parse_v2(out)["분류"] == "무관 중"
    assert not score_format_v2(out)["rules"]["R6_enum_valid"]


def test_h0_leaves_human_review_actions():
    """이미 사람이 확인하는 처리면 바꾸지 않는다."""
    for act in ("긴급 사인 요청", "등록(재현 대기)", "정보 요청 후 보류"):
        assert apply(resp(pri="중소", act=act), "B", "내부 QA")[1] == []


def test_h0_ignores_module_only_error():
    """모듈 오류는 담당자 배정 문제이고 처리 판단과 무관하므로 H-0 대상이 아니다."""
    src = resp(act="개발 배정").replace("[모듈]: 클라이언트 안정성", "[모듈]: 매칭 시스템")
    assert apply(src, "B", "내부 QA")[1] == []
