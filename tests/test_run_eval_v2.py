"""run_eval_v2.py / prompt_v2.py 테스트 (모델은 호출하지 않는다)."""

import json
from pathlib import Path

from prompt_v2 import SYSTEM_PROMPT_V2, build_input, build_prompt
from run_eval_v2 import OPTIONS_V2, check_split_guard, options_for, select_items

ROOT = Path(__file__).resolve().parent.parent
DATA = json.loads((ROOT / "data/eval_v13/aether_raid_v13.json").read_text(encoding="utf-8"))


def test_default_dev_split_counts():
    assert len(select_items(DATA, "dev", "all")) == 32
    assert len(select_items(DATA, "dev", "representative")) == 20
    assert all(i["split"] == "dev" for i in select_items(DATA, "dev", "all"))


def test_test_split_requires_final_flag():
    """평가용 문항은 --final 없이 실행되지 않는다 (설계 의도 1)."""
    assert check_split_guard("test", final=False)
    assert check_split_guard("all", final=False)
    assert check_split_guard("test", final=True) is None
    assert check_split_guard("dev", final=False) is None


def test_options_fix_context_and_seed():
    assert OPTIONS_V2["num_ctx"] == 8192
    assert options_for(1, 2)["seed"] == 2 and "seed" not in OPTIONS_V2


def test_no_dataset_text_leaks_into_system_prompt():
    """평가 문항의 제목·본문이 프롬프트 규칙에 들어가 있으면 점수가 부풀어 측정이 무의미하다."""
    for item in DATA["items"]:
        assert item["input"]["title"] not in SYSTEM_PROMPT_V2
        # 양식 머리글([테스트 환경] 등)을 뺀 본문에서 가장 긴 줄을 그 문항의 고유 문장으로 본다
        lines = [l for l in item["input"]["body"].split("\n") if l.strip() and not l.startswith("[")]
        longest = max(lines, key=len)[:30] if lines else ""
        assert not longest or longest not in SYSTEM_PROMPT_V2


def test_input_contains_track_and_context():
    a, b = next(i for i in DATA["items"] if i["track"] == "A"), next(i for i in DATA["items"] if i["track"] == "B")
    ta, tb = build_input(a), build_input(b)
    assert "(A) 커뮤니티 제보 원문" in ta and "[게시 일시]" in ta and "[참고: 기존 등록 이슈]" in ta
    assert "(B) QA 작성 BTS 이슈" in tb and "[작성자]" in tb and "[재현율]" in tb
    assert build_prompt(a).startswith(SYSTEM_PROMPT_V2)
