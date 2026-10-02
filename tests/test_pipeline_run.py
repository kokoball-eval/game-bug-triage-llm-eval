"""run.py / prompt.py 테스트 (모델은 호출하지 않는다)."""

import json
from pathlib import Path

from triage_eval.pipeline.contract import ENUMS_V2, MODULES, NO_MODULE, enum_errors, parse_v2
from triage_eval.pipeline.prompt import SYSTEM_PROMPT_V2, build_input, build_prompt, build_retry_prompt
from triage_eval.pipeline.run import OPTIONS_V2, check_split_guard, generate_triage, generate_with_retry, options_for, select_items

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


GOOD = "\n".join(["[요약]: 접속 시 튕김", "[분류]: 결함", "[모듈]: 클라이언트 안정성", "[우선순위]: Major",
                  "[재현 정보]: 충분", "[발생 빈도]: 항상", "[처리]: 등록(재현 대기)", "[누락 정보 및 권장 조치]: 로그 확인"])
BAD = GOOD.replace("[우선순위]: Major", "[우선순위]: 중소")


class FakeClient:
    """모델 대신 정해진 응답을 차례로 돌려준다. 받은 프롬프트를 기록한다."""

    def __init__(self, *responses):
        self.responses, self.prompts, self.formats, self.thinks = list(responses), [], [], []

    def generate(self, model, prompt, options, format=None, think=None):
        self.thinks.append(think)
        self.prompts.append(prompt)
        self.formats.append(format)
        return {"response": self.responses.pop(0), "eval_count": 100, "eval_duration": 10**9, "prompt_eval_count": 2400}

    def ps(self):
        return {"models": []}


def test_no_retry_when_format_is_valid():
    client = FakeClient(GOOD)
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert not res["retried"] and len(client.prompts) == 1


def test_retry_fixes_only_invalid_field():
    """틀린 필드만 다시 받아 그 줄에 넣는다. 재요청이 다른 필드를 다르게 말해도 반영하지 않는다."""
    client = FakeClient(BAD, '{"우선순위": "Minor", "분류": "버그 아님"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {"num_predict": 512})
    assert res["retried"] and res["retry_adopted"]
    assert res["response_text"] == GOOD.replace("[우선순위]: Major", "[우선순위]: Minor")
    assert res["attempts"][1]["fixed"] == {"우선순위": "Minor"}
    assert len(client.prompts) == 2 and res["elapsed_sec"] >= res["attempts"][0]["elapsed_sec"]


def test_retry_rechecks_action_when_judgment_field_was_invalid():
    """분류가 틀렸으면 처리도 다시 받는다 (v2.3 A10: 분류 '무관 중' + 폐기)."""
    bad = GOOD.replace("[분류]: 결함", "[분류]: 무관 중").replace("[처리]: 등록(재현 대기)", "[처리]: 폐기")
    client = FakeClient(bad, '{"분류": "결함", "처리": "정보 요청 후 보류"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert res["attempts"][1]["recheck"] == ["처리"] and "[처리]는 위 필드를 고친 뒤" in client.prompts[1]
    assert parse_v2(res["response_text"])["분류"] == "결함"
    assert parse_v2(res["response_text"])["처리"] == "정보 요청 후 보류"


def test_module_error_does_not_recheck_action():
    bad = GOOD.replace("[모듈]: 클라이언트 안정성", "[모듈]: 매칭 시스템")
    client = FakeClient(bad, '{"모듈": "게임플레이·밸런스", "처리": "폐기"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert res["attempts"][1]["recheck"] == []
    assert parse_v2(res["response_text"])["처리"] == "등록(재현 대기)"   # 요청하지 않은 처리 변경은 무시


def test_retry_with_invalid_value_keeps_first_response():
    client = FakeClient(BAD, '{"우선순위": "중간"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert res["retried"] and not res["retry_adopted"] and res["response_text"] == BAD


def test_retry_not_adopted_when_reply_is_garbage():
    client = FakeClient(BAD, "형식이 완전히 깨진 응답")
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert res["retried"] and not res["retry_adopted"] and res["response_text"] == BAD


def test_retry_disabled():
    client = FakeClient(BAD)
    res = generate_with_retry(client, "m", DATA["items"][0], {}, retry=False)
    assert not res["retried"] and res["response_text"] == BAD


def test_retry_prompt_names_field_without_hinting_answer():
    """재요청 안내문은 틀린 필드와 허용 값 목록만 알려 준다. 특정 값을 정답으로 고르지 않는다."""
    item = DATA["items"][0]
    errors = enum_errors(parse_v2(BAD))
    assert errors == [("우선순위", "중소")]
    p = build_retry_prompt(item, BAD, errors)
    assert p.startswith(build_prompt(item)) and "'중소'" in p
    note = p[len(build_prompt(item)):]
    assert "허용 값: Critical, Major, Minor, Trivial, 판단보류, 해당 없음" in note
    for label in item["labels"]["우선순위"]:
        assert f"{label}로" not in note and f"{label}(으)로" not in note


def test_recheck_only_is_not_counted_as_adopted():
    """틀렸던 필드는 그대로이고 함께 다시 받은 [처리]만 받아지면 채택으로 세지 않는다 (v2.3 A17 사례)."""
    bad = GOOD.replace("[분류]: 결함", "[분류]: 무관 중").replace("[처리]: 등록(재현 대기)", "[처리]: 폐기")
    client = FakeClient(bad, '{"분류": "무관 중", "처리": "폐기"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert res["retried"] and not res["retry_adopted"] and res["attempts"][1]["fixed"] == {"처리": "폐기"}


def test_retry_uses_enum_schema_only_for_retry():
    """설계 의도 6 — 첫 호출은 제한하지 않고, 재요청만 허용 값 enum 스키마로 제한한다."""
    bad = GOOD.replace("[분류]: 결함", "[분류]: 무관 중")
    client = FakeClient(bad, '{"분류": "무관", "처리": "등록(재현 대기)"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert client.formats[0] is None
    schema = client.formats[1]
    assert schema["properties"]["분류"]["enum"] == ENUMS_V2["분류"] and "무관 중" not in schema["properties"]["분류"]["enum"]
    assert schema["required"] == ["분류", "처리"]
    assert parse_v2(res["response_text"])["분류"] == "무관" and res["retry_adopted"]


def test_retry_with_unreadable_json_keeps_first_response():
    client = FakeClient(BAD, "[우선순위]: Minor")   # JSON이 아니면 반영하지 않는다
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert res["response_text"] == BAD and not res["retry_adopted"]


def test_module_schema_lists_single_modules():
    from triage_eval.pipeline.run import retry_schema
    s = retry_schema(["모듈"])
    assert s["properties"]["모듈"]["enum"] == MODULES + [NO_MODULE]


DISCARD = GOOD.replace("[분류]: 결함", "[분류]: 무관").replace("[처리]: 등록(재현 대기)", "[처리]: 폐기")


def test_discard_check_holds_when_model_sees_report():
    """설계 의도 7 — 폐기 직전 확인에서 '이상 현상 제보'면 정보 요청 후 보류로 바꾼다. 분류는 그대로 둔다."""
    client = FakeClient(DISCARD, '{"판정": "이상 현상 제보"}')
    res = generate_triage(client, "m", DATA["items"][0], {})
    assert res["discard_checked"] and res["discard_held"]
    assert parse_v2(res["response_text"])["처리"] == "정보 요청 후 보류"
    assert parse_v2(res["response_text"])["분류"] == "무관"
    assert client.formats[1]["properties"]["판정"]["enum"] == ["이상 현상 제보", "무관"]
    assert "[확인 질문]" in client.prompts[1] and res["attempts"][-1]["kind"] == "discard_check"


def test_discard_check_keeps_discard_for_irrelevant():
    client = FakeClient(DISCARD, '{"판정": "무관"}')
    res = generate_triage(client, "m", DATA["items"][0], {})
    assert res["discard_checked"] and not res["discard_held"]
    assert parse_v2(res["response_text"])["처리"] == "폐기"


def test_discard_check_skips_duplicates_and_other_actions():
    dup = DISCARD.replace("[분류]: 무관", "[분류]: 중복 의심")
    for text in (dup, GOOD):
        client = FakeClient(text)
        res = generate_triage(client, "m", DATA["items"][0], {})
        assert not res["discard_checked"] and len(client.prompts) == 1


def test_discard_check_unreadable_answer_keeps_first_decision():
    """확인 답을 읽을 수 없으면 바꾸지 않는다. 판단은 모델의 몫이고, 코드는 답이 있을 때만 따른다."""
    client = FakeClient(DISCARD, "모르겠습니다")
    res = generate_triage(client, "m", DATA["items"][0], {})
    assert res["discard_checked"] and not res["discard_held"]


def test_discard_check_runs_after_format_retry():
    """'무관 중' → 재요청으로 '무관' + 폐기 → 폐기 확인 (v2.3 A10 사례의 전체 흐름)."""
    bad = DISCARD.replace("[분류]: 무관", "[분류]: 무관 중")
    client = FakeClient(bad, '{"분류": "무관", "처리": "폐기"}', '{"판정": "이상 현상 제보"}')
    res = generate_triage(client, "m", DATA["items"][0], {})
    assert [a["kind"] for a in res["attempts"]] == ["first", "retry", "discard_check"]
    assert parse_v2(res["response_text"])["처리"] == "정보 요청 후 보류"


def test_discard_check_question_has_no_dataset_text():
    from triage_eval.pipeline.prompt import build_discard_check_prompt
    q = build_discard_check_prompt(DATA["items"][0])[len(build_prompt(DATA["items"][0])):]
    for item in DATA["items"]:
        assert item["input"]["title"] not in q


HAN = GOOD.replace("[요약]: 접속 시 튕김", "[요약]: 접속 시 과熱 후 튕김")


def test_r7_retry_rewrites_only_summary():
    """R7 — 다른 문자가 섞인 자유 서술 필드만 다시 받는다 (v2.3 seed 11 A10 '과熱' 사례)."""
    client = FakeClient(HAN, '{"요약": "접속 시 과열 후 튕김"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert res["retried"] and res["retry_adopted"]
    assert parse_v2(res["response_text"])["요약"] == "접속 시 과열 후 튕김"
    from triage_eval.pipeline.contract import LINE_PATTERNS
    assert client.formats[1]["properties"]["요약"] == {"type": "string", "pattern": LINE_PATTERNS["ko"]}
    assert "'熱'" in client.prompts[1] and res["attempts"][1]["lang_errors"] == [{"field": "요약", "chars": "熱"}]


def test_r7_retry_rejects_still_foreign_or_multiline():
    for reply in ('{"요약": "접속 시 過熱"}', '{"요약": "접속 시\\n과열"}'):
        client = FakeClient(HAN, reply)
        res = generate_with_retry(client, "m", DATA["items"][0], {})
        assert res["retried"] and not res["retry_adopted"] and res["response_text"] == HAN


def test_r6_and_r7_in_one_retry():
    both = HAN.replace("[우선순위]: Major", "[우선순위]: 미기재")
    client = FakeClient(both, '{"우선순위": "판단보류", "처리": "정보 요청 후 보류", "요약": "접속 시 과열 후 튕김"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert len(client.prompts) == 2
    assert client.formats[1]["required"] == ["우선순위", "처리", "요약"]
    out = parse_v2(res["response_text"])
    assert out["우선순위"] == "판단보류" and out["요약"] == "접속 시 과열 후 튕김"


def test_r7_outside_fields_is_not_retried():
    """필드 라벨까지 다른 언어로 바뀐 응답은 고칠 필드가 없어 재요청하지 않는다."""
    broken = GOOD.replace("[요약]: 접속 시 튕김", "[概要]: 游戏崩溃")
    client = FakeClient(broken)
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    assert not res["retried"] and len(client.prompts) == 1 and res["response_text"] == broken


def test_line_pattern_matches_allowlist():
    """JSON 스키마 pattern 은 R7 허용 목록과 같은 문자 집합에서 줄바꿈·큰따옴표·역슬래시만 뺀 것이다."""
    import re
    from triage_eval.pipeline.contract import FORBIDDEN_SCRIPTS, LINE_PATTERNS
    pat = re.compile(LINE_PATTERNS["ko"])
    for ok in ("폰 업데이트 이후 10분만에 과열", "계정·로그인 → ① ★ 50%", "Critical (SSR) PvP: 재현 3/3 [참고]"):
        assert pat.match(ok) and not FORBIDDEN_SCRIPTS["ko"].search(ok)
    for bad in ("과熱", "줄\n바꿈", '따옴표"', "역슬래시\\", ""):
        assert not pat.match(bad)


class PatternRejectingClient(FakeClient):
    """pattern 을 지원하지 않는 실행 환경 — pattern 이 든 스키마를 받으면 오류를 낸다."""

    def generate(self, model, prompt, options, format=None, think=None):
        if format and any("pattern" in v for v in format.get("properties", {}).values()):
            self.prompts.append(prompt)
            self.formats.append(format)
            raise RuntimeError("unsupported schema: pattern")
        return super().generate(model, prompt, options, format, think)


def test_pattern_fallback_when_unsupported():
    client = PatternRejectingClient(HAN, '{"요약": "접속 시 과열 후 튕김"}')
    res = generate_with_retry(client, "m", DATA["items"][0], {})
    retry = res["attempts"][1]
    assert retry["pattern_fallback"] and "pattern" in retry["pattern_error"]
    assert "pattern" not in client.formats[-1]["properties"]["요약"]
    assert parse_v2(res["response_text"])["요약"] == "접속 시 과열 후 튕김"


def test_every_call_turns_thinking_off():
    """설계 의도 8 — 첫 응답과 재요청 모두 think=False 로 부른다."""
    client = FakeClient(BAD, '{"우선순위": "Minor", "분류": "버그 아님"}')
    generate_with_retry(client, "m", DATA["items"][0], {"num_predict": 512})
    assert len(client.thinks) == 2 and all(t is False for t in client.thinks)
