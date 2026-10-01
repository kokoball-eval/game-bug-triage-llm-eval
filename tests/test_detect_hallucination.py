"""detect_hallucination.py 환각(근거 없는 구체 사실) 탐지 테스트.

탐지기는 게이트의 합격 기준이 되므로 두 방향을 모두 고정한다.
- 놓치면 안 되는 것: v1.0·9/30 재실행에서 실제로 나온 Llama Q08 날조 4건
- 잡으면 안 되는 것: 입력에 근거가 있는 사실, 정보를 "요청"하는 문맥, 선택지 필드
"""

import json
from pathlib import Path

import pytest

from detect_hallucination import detect, is_grounded, load_questions, scan_log

from conftest import BASELINE_FILE, ROOT

HISTORY_0930 = ROOT / "data" / "results" / "history" / "local_eval_results_20260930_154355.json"
CLOUD_FILE = ROOT / "data" / "results" / "cloud_eval_results.json"


def response(summary: str, missing: str, severity: str = "판단보류", repro: str = "불명확") -> str:
    return "\n".join([
        f"[요약]: {summary}",
        "[모듈]: 시스템",
        f"[심각도]: {severity}",
        f"[재현 여부]: {repro}",
        f"[누락 정보 및 권장 조치]: {missing}",
    ])


# ── 1. 잡아야 하는 것 ──────────────────────────────────────

@pytest.mark.parametrize("missing, category", [
    ("확인 필요 기기: Windows 10, Intel Core i5", "os"),
    ("NVIDIA GeForce GTX 1660 Ti 환경에서 발생", "hardware"),
    ("갤럭시 S23에서 재현됨", "device"),
    ("v2.4.0 빌드에서 확인", "version"),
    ("게임 시작 후 10분 이내에 오류 발생", "quantity"),
    ("WASD 키를 반복 입력하면 발생", "input"),
])
def test_each_category_is_caught_when_not_in_input(missing, category):
    result = detect(response("앱 강제 종료", missing), report_text="크래시남")
    assert result["hallucinated"] is True
    assert category in {u["category"] for u in result["ungrounded"]}


def test_summary_field_is_also_scanned():
    result = detect(response("Windows 10에서 앱 강제 종료", "추가 정보 필요"), report_text="크래시남")
    assert result["ungrounded"][0]["field"] == "요약"


# ── 2. 잡으면 안 되는 것 ───────────────────────────────────

def test_fact_present_in_input_is_grounded():
    report = "전투 중 보스 패턴 3단계 진입 시 크래시. iOS 17.4, v2.3.1에서 확인."
    result = detect(response("iOS 17.4에서 크래시", "v2.3.1 회귀 테스트 권장"), report)
    assert result["hallucinated"] is False


def test_reordered_tokens_are_grounded():
    """입력 "갤럭시 기종(S21)" → 응답 "갤럭시 S21" 은 근거 있음 (설계 의도 3)."""
    assert is_grounded("갤럭시 S21", "device", "특정 갤럭시 기종(S21)에서만 텍스처가 깨짐")


def test_quantity_must_match_exactly():
    """수치는 토큰 일부 일치로 넘기지 않는다. 입력의 "15초"가 응답의 "5초"를 정당화하지 않는다."""
    assert not is_grounded("5초", "quantity", "15초 후에 멈춤")
    assert is_grounded("15초", "quantity", "15초 후에 멈춤")


@pytest.mark.parametrize("missing", [
    "OS: Windows 10/11/Android/iOS 중 택1 확인 필요",          # 슬래시 나열 + 선택지
    "확인할 기기: 갤럭시 S23/아이폰 15",                        # 슬래시 나열만
    "사용 기기(예: 갤럭시 S23)와 OS 버전 확인 필요",            # 예시
    "iOS 17 또는 Android 14 중 어느 환경인지 확인",             # 또는
])
def test_request_context_is_hedged_not_hallucinated(missing):
    """정보를 요청하는 것은 트리아지의 정상 동작이다 (설계 의도 4)."""
    result = detect(response("앱 강제 종료 제보", missing), report_text="크래시남")
    assert result["hallucinated"] is False
    assert result["hedged"]


def test_enum_fields_are_not_scanned():
    """[재현 여부]: 발생(100%) 의 100% 를 수치 날조로 오인하지 않는다."""
    result = detect(response("앱 강제 종료", "추가 정보 필요", severity="Blocker", repro="발생(100%)"),
                    report_text="크래시남")
    assert result["hallucinated"] is False


@pytest.mark.parametrize("text", ["", None, "형식이 깨진 응답"])
def test_empty_or_broken_response_does_not_crash(text):
    assert detect(text, "크래시남")["hallucinated"] is False


# ── 3. 실제 로그로 고정 (골든 테스트) ─────────────────────

@pytest.fixture(scope="module")
def questions():
    return load_questions(ROOT)


def flagged(path: Path, questions) -> set[str]:
    return {r["eval_id"] for r in scan_log(path, questions) if r["hallucinated"]}


def test_known_llama_q08_fabrications_are_all_caught(questions):
    """KL-001 의 날조 4건(v1.0 2건 + 9/30 재실행 2건)을 하나도 놓치지 않아야 한다."""
    expected = {"llama3.1_8b_Q08_run1", "llama3.1_8b_Q08_run2"}
    assert flagged(BASELINE_FILE, questions) == expected
    assert flagged(HISTORY_0930, questions) == expected


def test_no_false_positive_on_qwen_and_cloud(questions):
    """Qwen 40건과 Cloud 5건에서 오탐이 없어야 한다 (채택 모델이 오탐으로 FAIL 나면 게이트를 못 믿는다)."""
    for path in (BASELINE_FILE, HISTORY_0930):
        assert not {i for i in flagged(path, questions) if i.startswith("qwen")}
    assert flagged(CLOUD_FILE, questions) == set()


def test_llama_q02_option_list_is_hedged(questions):
    """Llama Q02 의 "OS: Windows 10/11/Android/iOS 중 택1" 은 요청 문맥으로 분류돼야 한다."""
    rows = {r["eval_id"]: r for r in scan_log(BASELINE_FILE, questions)}
    q02 = rows["llama3.1_8b_Q02_run1"]
    assert q02["hallucinated"] is False
    assert [h["entity"] for h in q02["hedged"]] == ["Windows 10"]
