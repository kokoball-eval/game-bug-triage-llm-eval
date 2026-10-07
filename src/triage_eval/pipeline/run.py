"""평가셋 실행 스크립트 — 출력 형식 v2. v1.3 평가셋(기본)과 v1.4 평가셋을 실행한다.

사용법:
    uv run triage-run --seed 1 --strict-env                 # 개발용(dev) 전체, 현재 선정 모델(qwen2.5:7b)
    uv run triage-run --seed 1 --model qwen2.5:7b --model gemma4:12b   # 모델 비교 (v1.4, triage-select 로 판정)
    uv run triage-run --seed 1 --set focused                # 집중 세트만
    uv run triage-run --seed 1 --split test --final         # 평가용(test) — 최종 측정 때만
    uv run triage-run --seed 1 --dataset v14                # (v1.4) 개발용 63건
    uv run triage-run --seed 1 --dataset v14 --split final --final   # (v1.4) 최종 평가용 25건 — 방법 선택 후 1회만
    uv run triage-run --seed 1 --dataset v14 --method m2    # (v1.4) 방법 M2 (m0·m1·m2·m1m2, 설계 의도 12)

출력:
    data/results/v13/history/v13_<split>_<시각>.json   실행 기록 (항상 새 파일)
    data/results/v14/history/v14_<split>_<방법>_<시각>.json   --dataset v14 실행 기록

채점: uv run triage-score

[설계 의도]
1. 기본 대상은 개발용(dev)이다. 평가용(test)은 --final 을 함께 줘야만 실행된다.
   프롬프트를 고치면서 test 점수를 보면, test에 맞춰 프롬프트를 고치게 되어 최종 수치를 믿을 수 없게 된다.
   "실수로 test를 돌리는 일"을 사람의 주의가 아니라 실행 조건으로 막는다.
2. 모델 호출 방식(generate + 문자열 결합, 워밍업 분리, 실패 시 다음 문항 진행)과
   실행 조건 기록(run_config), 측정 환경 점검은 v1 run_eval.py 와 같다.
   지문·digest·VRAM 측정 같은 공용 함수는 run_eval.py 에서 가져오되, run_eval.py 자체는 수정하지 않는다.
   v1 로그 형식이 바뀌면 v1 기준선과의 회귀 비교가 흔들리기 때문이다. v2에서 추가로 필요한
   입력 토큰 수(prompt_eval_count) 기록은 이 파일의 generate_once() 에서 한다.
3. num_ctx 를 8192로 명시한다. v2 프롬프트는 판정 규칙이 들어가 v1보다 길어서(약 3,000자),
   기본값 4,096 토큰에 출력까지 더하면 넘칠 수 있다. Ollama는 넘친 앞부분을 조용히 잘라 내므로,
   잘린 채 실행되면 "규칙을 못 지킨 모델"로 잘못 측정된다. 회차마다 입력 토큰 수(prompt_eval_count)를 기록하고,
   입력+출력 상한이 num_ctx 를 넘을 수 있으면 경고한다.
4. num_predict 를 512로 둔다. v2는 필드가 8개라 v1(350)보다 출력이 길다.
   잘린 응답은 형식 채점에서 R2(필드 누락)로 드러나므로, 상한에 걸린 회차 수도 기록한다.
5. 모델 응답에 후처리 안전장치(guardrail.py)를 적용한 결과를 response_text 로 기록하고,
   모델 원본은 raw_response_text 에 남긴다. 채점·게이트는 실제 BTS에 들어가는 response_text 를 판정한다.
   --no-guardrail 을 주면 원본을 그대로 기록한다(모델 단독 성능 측정용).
6. 응답이 R6(허용 값)을 어기면 틀린 필드와 허용 값을 알려 주고, 그 필드만 1회 다시 요청한다(generate_with_retry).
   - 응답 전체가 아니라 틀린 필드만 다시 받는다. 전체를 다시 생성하면 형식에 문제가 없던 다른 필드의 판단까지
     바뀔 수 있다(v2.1 대비 응답 64개 중 프롬프트 v2.2는 29개, v2.3은 49개가 바뀌었다). 생성 길이도 짧아
     재요청 비용이 작다(num_predict 128 — 필드 6개를 모두 다시 받아도 JSON이 잘리지 않는 길이). eval_count·tokens_per_sec·hit_num_predict 는 첫 응답 기준이다.
   - 분류·우선순위·재현 정보 중 하나가 틀렸으면 [처리]도 함께 다시 정하게 한다. 처리는 그 판단에서 정해지므로,
     분류만 고치면 "결함인데 폐기" 같은 앞뒤가 맞지 않는 응답이 남는다.
   - 재요청 응답은 JSON 스키마로 제한한다(Ollama 구조화 출력, format=스키마). 각 필드의 값은 허용 값 목록(enum)
     안에서만 생성되므로 '무관 중' 같은 값이 재요청 결과로 나올 수 없다. 프롬프트 v2.3에서는 텍스트 재요청이
     '무관 중'을 그대로 되풀이했고(A17, seed 3쌍 모두), 선택지 표기를 고친 v2.4는 판단 품질을 떨어뜨려 기각했다.
     첫 응답은 제한하지 않는다. 8개 필드 전체를 JSON으로 받으면 출력 형식 자체가 바뀌어 기준선과 비교할 수 없다.
     [모듈] 재요청은 단일 모듈만 고를 수 있다(복합 병기 "A/B"는 enum으로 표현하지 않는다).
   - 새 값은 모델이 고른다. 코드는 그 값이 허용 값일 때만 첫 응답의 해당 줄에 넣고, 아니면 첫 응답을 그대로 둔다.
     허용 값 밖인 값을 코드가 비슷한 값으로 바꾸지 않는다. 스키마 제한과 별개로 이 검증을 유지해,
     구조화 출력이 지원되지 않는 환경에서도 잘못된 값이 들어가지 않게 한다.
   - 첫 응답·재요청 응답·고쳐진 필드를 attempts 에 남기고, elapsed_sec 는 두 호출 시간의 합으로 기록한다.
     재요청에 드는 시간은 실제 운영에서도 드는 비용이므로 지연 측정에서 빼지 않는다.
   - 재요청은 같은 seed로 호출한다. 프롬프트가 달라지므로 응답이 바뀌고, 같은 조건으로 다시 실행하면 재현된다.
   - 출력 언어 위반(R7)도 같은 방식으로 재요청한다. 다른 문자가 섞인 자유 서술 필드([요약], [누락 정보 및 권장 조치])만
     한국어로 다시 쓰게 하고, 새 값이 한 줄이며 출력 언어 밖 문자가 없을 때만 넣는다. 자유 서술은 enum 으로 제한할 수
     없으므로 허용 문자 패턴(JSON 스키마 pattern, contract.LINE_PATTERNS)으로 제한하고, 받은 뒤에도 다시 검증한다.
     처음에는 문자열 제한 없이 "한국어로 다시 쓰라"고만 했는데, v2.3 seed 11 A10에서 모델이 '과熱'을 그대로 되풀이했다
     ('무관 중'을 텍스트 재요청이 고치지 못한 것과 같은 현상). 실행 환경이 pattern 을 지원하지 않아 호출이 실패하면
     pattern 없이 한 번 더 호출하고 그 사실을 기록한다. 지금까지 측정된 R7 위반 6건은 모두 [요약]에서 시작했다
     (v2.3 seed 11의 '과熱' 등). 응답 전체가 다른 언어로 넘어가 필드 라벨까지 사라진 경우는 고칠 필드가 없어
     재요청하지 않고, 형식 위반으로 남는다. num_predict 는 자유 서술을 다시 받을 수 있게 256으로 둔다.
   --no-retry 를 주면 재요청하지 않는다.
7. 최종 [처리]가 폐기이고 [분류]가 중복 의심이 아니면, 폐기 직전에 확인 질문을 1회 한다(discard_check).
   - 판정 기준서 H-9("결함일 가능성이 있는 제보는 폐기하지 않는다. 확신이 없으면 보류")를 실행 단계로 옮긴 것이다.
     폐기는 되돌릴 수 없고 아무도 다시 보지 않는 처리라, 이 처리에만 확인 단계를 둔다.
   - 확인 답은 JSON 스키마로 "이상 현상 제보 / 무관" 중 하나만 나오게 한다. "이상 현상 제보"면 [처리]를
     정보 요청 후 보류로 바꾼다. [분류]는 모델의 첫 판단을 그대로 남겨, 분류 오답은 채점에 그대로 드러나게 한다.
   - 중복 의심은 제외한다. 중복 건은 결함 정보가 있어도 기존 이슈에 덧붙이고 폐기하는 것이 규칙(H-6)이므로
     이 질문으로는 가를 수 없다.
   - 도입 근거: 형식 재요청으로 '무관 중'이 '무관'으로 고쳐지자, 그 뒤에 가려져 있던 판단 오류
     (발열 제보 A10을 무관으로 보고 폐기, X-2)가 드러났다 (docs/issue_log.md ISSUE-007).
   - 확인 질문과 답은 attempts 에 남기고, 호출 시간은 elapsed_sec 에 더한다.
   --no-discard-check 를 주면 확인하지 않는다.
8. (v1.4) 모든 모델 호출에 think=False 를 넘기고 실행 기록에 남긴다(run_config.think).
   최근 모델은 기본 상태에서 생각 과정을 먼저 출력하는데(사전 점검: qwen3.5·gemma4 계열 모두), 켜 두면 8칸 형식과
   지연이 모두 달라진다. 생각 기능이 없는 qwen2.5:7b 는 이 인자를 거부하지 않는 것을 사전 점검으로 확인했고,
   응답이 바뀌지 않는지는 v1.3 실행 기록과 대조해 확인한다.
9. (v1.4) 모델마다 실행 전에 그 모델을 메모리에서 내린다(keep_alive=0). 같은 seed라도 Ollama가 직전에 다른 프롬프트를
   처리했으면 응답이 재현되지 않으므로(docs/issue_log.md OBS-002), 사람이 실행 전에 하던 ollama stop 을 코드가 한다.
   여러 모델을 한 번에 실행해도 모델마다 같은 출발 상태에서 측정된다.
10. (v1.4) 기본 대상은 현재 선정 모델 하나다. Llama 3.1은 평가용 세트에서도 형식·Critical 인식 모두 크게 뒤져
   정기 측정에서 뺐다(필요하면 --model 로 지정). 후보 모델은 --model 로 함께 넘겨 같은 실행 안에서 비교한다.
11. (v1.4) --dataset 으로 평가셋을 고른다. 기본값은 v13이라 옵션을 주지 않으면 v1.3과 똑같이 동작한다.
   - v1.4 평가셋(data/eval_v14/)은 v1.3의 63건이 모두 dev이고, 새 25건의 분할 이름이 final 이다.
     final 도 test 와 같이 --final 이 있어야 실행된다(설계 의도 1을 그대로 적용).
   - 고른 평가셋에 없는 분할(v13의 final, v14의 test)을 지정해 문항이 0건이면 실행하지 않고 종료 코드 2로 끝낸다.
     빈 실행 기록이 남으면 "실행은 했는데 결과가 없음"과 "실행하지 않음"이 구분되지 않기 때문이다.
   - 실행 기록은 평가셋별 폴더(v13/history, v14/history)에 따로 남긴다. v1.3 게이트·모델 선정 도구는
     v13 폴더만 보므로, v1.4 실행 기록이 섞여 v1.3 판정이 바뀌는 일이 없다.
12. (v1.4) --method 로 방법을 고른다(methods.py, report/method_comparison_v14_plan.md). 기본값 m0은 기존과 같다.
   - m1·m1m2: 판정 예시 블록을 시스템 프롬프트 뒤에 넣는다. 형식 재요청·폐기 확인·Critical 확인 질문도 같은 앞부분을 쓴다.
   - m2·m1m2: 형식 재요청 뒤, 폐기 확인 앞에 Critical 체크리스트를 1회 묻는다(critical_check). 순서를 이렇게 둔 것은
     형식이 고쳐진 판단을 보고 묻기 위해서이고, 폐기 확인·후처리 안전장치는 모든 방법에서 같은 위치에 두기 위해서다.
   - m0이 아닌 방법은 v14 평가셋에서만 실행한다. v1.3 실행 기록 폴더에는 m0 실행만 남아 v1.3 게이트가 흔들리지 않는다.
   - 실행 기록 run_config 에 method 와 방법 구성 지문(method_assets_sha256)을 남긴다. 비교 도구(compare.py)는
     방법 말고 다른 조건이 같은지 확인할 때 이 값을 쓴다.
13. (v1.5) 모든 응답을 받은 뒤 사용한 모델을 모두 메모리에서 내린다. Ollama는 마지막 모델을 기본 5분간 유지하는데,
   남은 모델이 다음 실행의 측정 환경 점검에서 "다른 프로그램의 VRAM 사용"으로 잡혀 --strict-env 가 실행을
   거부했다(docs/issue_log.md ISSUE-011). 응답을 다 받은 뒤에 내리므로 응답 내용에는 영향이 없고,
   run_config 에 항목을 더하지 않아 기존 실행 기록과의 비교 조건도 바뀌지 않는다.
   실행을 중간에 멈춘 경우는 내리지 않는다. 그때는 측정 환경 점검의 안내대로 ollama stop 으로 내린다.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

import time

import ollama

from triage_eval.common.ollama_runtime import get_model_digests, get_vram_mib, sha256_text
from triage_eval.common.paths import ROOT
from triage_eval.common.preflight import snapshot as preflight_snapshot
from triage_eval.pipeline.contract import (ENUMS_V2, FORBIDDEN_SCRIPTS, LINE_PATTERNS, MODULES, NO_MODULE, OUTPUT_LANG,
                                           enum_errors, language_errors, parse_v2, replace_field, score_format_v2)
from triage_eval.pipeline import methods
from triage_eval.pipeline.guardrail import GUARDRAIL_VERSION, apply_record
from triage_eval.pipeline.prompt import (DISCARD_CHECK_CHOICES, PROMPT_VERSION, SYSTEM_PROMPT_V2,
                                         build_discard_check_prompt, build_prompt, build_retry_prompt)

DATASET = ROOT / "data" / "eval_v13" / "aether_raid_v13.json"   # 기본 평가셋 (screen.py 등 v1.3 도구가 사용)
OUT_DIR = ROOT / "data" / "results" / "v13" / "history"
DATASET_V14 = ROOT / "data" / "eval_v14" / "aether_raid_v14.json"   # 설계 의도 11
OUT_DIR_V14 = ROOT / "data" / "results" / "v14" / "history"

MODELS = ["qwen2.5:7b"]  # 설계 의도 10
THINK = False  # 설계 의도 8
REPEAT_COUNT = 2
OPTIONS_V2 = {"temperature": 0.2, "num_predict": 512, "num_ctx": 8192}
RECHECK_TRIGGER = ("분류", "우선순위", "재현 정보")  # 이 필드가 틀리면 [처리]도 다시 정한다
RETRY_POLICY = {"trigger": ["R6_enum_valid", "R7_output_language"], "max_retries": 1, "scope": "field",
                "output": "json_schema_enum+line_pattern", "num_predict": 256}  # 설계 의도 6


def rel(path: Path) -> str:
    """저장소 안이면 상대 경로, 밖이면(테스트 임시 폴더 등) 그대로 표시한다."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def select_items(dataset: dict, split: str, set_name: str) -> list[dict]:
    items = dataset["items"]
    if split != "all":
        items = [i for i in items if i["split"] == split]
    if set_name != "all":
        items = [i for i in items if i["set"] == set_name]
    return items


def generate_once(client, model: str, prompt: str, options: dict, schema: dict | None = None) -> dict:
    """완성된 프롬프트로 1회 생성한다. 측정 항목은 v1 execute_single_inference 와 같고 입력 토큰 수가 추가된다.
    schema 를 주면 응답을 그 JSON 스키마로 제한한다(재요청 전용, 설계 의도 6)."""
    start = time.perf_counter()
    try:
        extra = {"format": schema} if schema else {}
        r = client.generate(model=model, prompt=prompt, options=options, think=THINK, **extra)
        eval_ns = r.get("eval_duration", 0)
        return {
            "success": True,
            "response_text": r.get("response", "").strip(),
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "load_duration_sec": round(r.get("load_duration", 0) / 1e9, 3),
            "prompt_eval_count": r.get("prompt_eval_count"),
            "eval_count": r.get("eval_count", 0),
            "tokens_per_sec": round(r.get("eval_count", 0) / (eval_ns / 1e9), 2) if eval_ns > 0 else None,
            "vram_mib": get_vram_mib(client, model),
            "error_message": None,
        }
    except Exception as e:  # 한 건 실패로 배치 전체가 멈추지 않게 기록하고 넘어간다
        return {
            "success": False, "response_text": "", "elapsed_sec": round(time.perf_counter() - start, 3),
            "load_duration_sec": 0.0, "prompt_eval_count": None, "eval_count": 0, "tokens_per_sec": None,
            "vram_mib": get_vram_mib(client, model), "error_message": str(e),
        }


def retry_schema(fields: list[str], use_pattern: bool = True) -> dict:
    """재요청 필드만 담는 JSON 스키마 (설계 의도 6). 선택지 필드는 허용 값 enum, 자유 서술 필드는
    출력 언어 허용 문자만 쓰는 한 줄 문자열(pattern)로 제한한다."""
    def prop(f):
        if f in ENUMS_V2 or f == "모듈":
            return {"type": "string", "enum": ENUMS_V2.get(f) or (MODULES + [NO_MODULE])}
        return {"type": "string", "pattern": LINE_PATTERNS[OUTPUT_LANG]} if use_pattern else {"type": "string"}
    return {"type": "object", "properties": {f: prop(f) for f in fields}, "required": list(fields)}


def value_ok(field: str, value: str, merged_text: str) -> bool:
    """재요청 값을 넣어도 되는가. 선택지 필드는 허용 값(R6), 자유 서술 필드는 한 줄 + 출력 언어(R7)."""
    if field in ENUMS_V2 or field == "모듈":
        return all(f != field for f, _ in enum_errors(parse_v2(merged_text)))
    return "\n" not in value and not FORBIDDEN_SCRIPTS[OUTPUT_LANG].search(value)


def parse_retry(text: str) -> dict:
    """재요청 응답(JSON)을 읽는다. 읽을 수 없으면 빈 dict — 첫 응답이 그대로 남는다."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}
    return {k: v.strip() for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) else {}


def merge_retry(first_text: str, new_values: dict, fields: list[str]) -> tuple[str, dict]:
    """재요청에서 받은 값 중 다시 요청한 필드만, 허용 값일 때만 첫 응답의 그 줄에 넣는다 (설계 의도 6)."""
    out, fixed = first_text, {}  # 재요청 대상이 아닌 필드는 무시한다
    for field in fields:
        value = new_values.get(field)
        if not value:
            continue
        candidate = replace_field(out, field, value)
        if value_ok(field, value, candidate):
            out, fixed[field] = candidate, value
    return out, fixed


def unload_model(client, model: str) -> None:
    """설계 의도 9 — 모델을 메모리에서 내린다. 내릴 모델이 없거나 실패해도 실행은 계속한다."""
    try:
        client.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def generate_with_retry(client, model: str, item: dict, options: dict, retry: bool = True, examples: str = "") -> dict:
    """설계 의도 6 — 1회 생성하고, R6·R7 위반이면 틀린 필드만 1회 다시 요청한다."""
    first = generate_once(client, model, build_prompt(item, examples), options)
    if not first["success"]:
        return {**first, "attempts": [], "retried": False}
    fmt1 = score_format_v2(first["response_text"])
    attempts = [{"kind": "first", "response_text": first["response_text"], "failed_rules": fmt1["failed_rules"],
                 "elapsed_sec": first["elapsed_sec"]}]
    if not retry or not any(r in fmt1["failed_rules"] for r in RETRY_POLICY["trigger"]):
        return {**first, "attempts": attempts, "retried": False}

    values = parse_v2(first["response_text"])
    errors, lang_errs = enum_errors(values), language_errors(values)
    # 처리는 분류·우선순위·재현 정보 판단에서 정해지므로, 그중 하나가 틀렸으면 처리도 함께 다시 정하게 한다
    recheck = ("처리",) if any(f in RECHECK_TRIGGER for f, _ in errors) and all(f != "처리" for f, _ in errors) else ()
    fields = [f for f, _ in errors] + list(recheck) + [f for f, _ in lang_errs]
    if not fields:   # 위반이 필드 밖(필드 라벨이 아닌 줄 등)에 있으면 고칠 필드가 없다
        return {**first, "attempts": attempts, "retried": False}
    retry_opts = {**options, "num_predict": RETRY_POLICY["num_predict"]}
    retry_prompt = build_retry_prompt(item, first["response_text"], errors, recheck, lang_errs, examples=examples)
    second = generate_once(client, model, retry_prompt, retry_opts, schema=retry_schema(fields))
    pattern_fallback = False
    if not second["success"] and lang_errs:
        # 실행 환경의 문법 변환기가 pattern 을 지원하지 않아 호출이 실패하면, pattern 없이 다시 호출한다.
        # 같은 재요청의 일부로 보며 오류 내용과 두 호출 시간을 모두 남긴다. 받은 값은 value_ok 가 검증한다.
        pattern_error, failed_sec = second["error_message"], second["elapsed_sec"]
        second = generate_once(client, model, retry_prompt, retry_opts, schema=retry_schema(fields, use_pattern=False))
        second = {**second, "elapsed_sec": round(second["elapsed_sec"] + failed_sec, 3), "pattern_error": pattern_error}
        pattern_fallback = True
    merged, fixed = merge_retry(first["response_text"], parse_retry(second["response_text"]), fields) \
        if second["success"] else (first["response_text"], {})
    attempts.append({"kind": "retry", "response_text": second["response_text"], "elapsed_sec": second["elapsed_sec"],
                     "eval_count": second.get("eval_count", 0), "error_message": second["error_message"],
                     "errors": [{"field": f, "value": v} for f, v in errors], "recheck": list(recheck),
                     "lang_errors": [{"field": f, "chars": c} for f, c in lang_errs], "fixed": fixed,
                     "pattern_fallback": pattern_fallback, "pattern_error": second.get("pattern_error")})
    return {**first, "response_text": merged,
            "elapsed_sec": round(first["elapsed_sec"] + second["elapsed_sec"], 3),
            "attempts": attempts, "retried": True,
            # 채택 = 원래 틀렸던 필드가 고쳐졌는가. 함께 다시 받은 [처리]만 받아진 경우는 채택이 아니다
            "retry_adopted": any(f in fixed for f, _ in errors + lang_errs)}


DISCARD_CHECK_POLICY = {"trigger": "처리=폐기, 분류≠중복 의심", "choices": DISCARD_CHECK_CHOICES,
                        "on_report": "정보 요청 후 보류", "num_predict": 32}  # 설계 의도 7
DISCARD_CHECK_SCHEMA = {"type": "object", "properties": {"판정": {"type": "string", "enum": DISCARD_CHECK_CHOICES}},
                        "required": ["판정"]}


def discard_check(client, model: str, item: dict, res: dict, options: dict, examples: str = "") -> dict:
    """설계 의도 7 — 폐기 직전 확인. 대상이 아니면 res 를 그대로 돌려준다."""
    pred = parse_v2(res.get("response_text", ""))
    if not res.get("success") or pred.get("처리") != "폐기" or pred.get("분류") == "중복 의심":
        return {**res, "discard_checked": False}
    opts = {**options, "num_predict": DISCARD_CHECK_POLICY["num_predict"]}
    ans = generate_once(client, model, build_discard_check_prompt(item, examples), opts, schema=DISCARD_CHECK_SCHEMA)
    verdict = parse_retry(ans["response_text"]).get("판정") if ans["success"] else None
    held = verdict == "이상 현상 제보"
    text = replace_field(res["response_text"], "처리", DISCARD_CHECK_POLICY["on_report"]) if held else res["response_text"]
    attempts = res.get("attempts", []) + [{"kind": "discard_check", "response_text": ans["response_text"],
                                          "verdict": verdict, "held": held, "elapsed_sec": ans["elapsed_sec"],
                                          "error_message": ans["error_message"]}]
    return {**res, "response_text": text, "elapsed_sec": round(res["elapsed_sec"] + ans["elapsed_sec"], 3),
            "attempts": attempts, "discard_checked": True, "discard_held": held}


def critical_check(client, model: str, item: dict, res: dict, options: dict, examples: str = "") -> dict:
    """설계 의도 12 — Critical 체크리스트(M2). 분류가 결함일 때만 묻고, 올리기만 한다(methods.decide_upgrade)."""
    pred = parse_v2(res.get("response_text", ""))
    if not res.get("success") or not methods.should_ask(pred):
        return {**res, "critical_checked": False}
    opts = {**options, "num_predict": methods.CHECKLIST_POLICY["num_predict"]}
    prompt = methods.build_checklist_prompt(build_prompt(item, examples), res["response_text"])
    ans = generate_once(client, model, prompt, opts, schema=methods.CHECKLIST_SCHEMA)
    answers = parse_retry(ans["response_text"]) if ans["success"] else {}
    upgraded, reason = methods.decide_upgrade(pred, answers)
    text = methods.apply_upgrade(res["response_text"]) if upgraded else res["response_text"]
    attempts = res.get("attempts", []) + [{"kind": "critical_check", "response_text": ans["response_text"],
                                          "answers": answers, "upgraded": upgraded, "reason": reason,
                                          "elapsed_sec": ans["elapsed_sec"], "error_message": ans["error_message"]}]
    return {**res, "response_text": text, "elapsed_sec": round(res["elapsed_sec"] + ans["elapsed_sec"], 3),
            "attempts": attempts, "critical_checked": True, "critical_upgraded": upgraded}


def generate_triage(client, model: str, item: dict, options: dict, retry: bool = True, check: bool = True,
                    method: str = "m0") -> dict:
    """1회 생성 → 형식 재요청(설계 의도 6) → (M2) Critical 체크리스트 → 폐기 확인(설계 의도 7).
    후처리 안전장치는 main 에서 적용한다. method 는 설계 의도 12."""
    use_examples, use_checklist = methods.METHODS[method]
    examples = methods.examples_block() if use_examples else ""
    res = generate_with_retry(client, model, item, options, retry=retry, examples=examples)
    if use_checklist:
        res = critical_check(client, model, item, res, options, examples)
    return discard_check(client, model, item, res, options, examples) if check else {**res, "discard_checked": False}


def check_split_guard(split: str, final: bool) -> str | None:
    """설계 의도 1·11 — test·final 이 포함된 실행은 --final 이 있어야 한다. 막을 때는 이유를 돌려준다."""
    if split in ("test", "final", "all") and not final:
        return ("평가용(test·final) 문항은 최종 측정 때만 실행합니다. 프롬프트 개선은 --split dev 로 하고, "
                "최종 측정이면 --final 을 함께 주세요.")
    return None


def options_for(seed_base: int | None, run_idx: int) -> dict:
    return dict(OPTIONS_V2) if seed_base is None else {**OPTIONS_V2, "seed": seed_base + run_idx - 1}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="평가셋 실행 (출력 형식 v2)")
    p.add_argument("--dataset", choices=["v13", "v14"], default="v13", help="평가셋 (기본: v13, 설계 의도 11)")
    p.add_argument("--split", choices=["dev", "test", "final", "all"], default="dev")
    p.add_argument("--method", choices=list(methods.METHODS), default="m0", help="방법 (기본: m0, 설계 의도 12)")
    p.add_argument("--set", dest="set_name", choices=["representative", "focused", "all"], default="all")
    p.add_argument("--model", action="append", help="실행할 모델 (여러 번 지정 가능, 기본: qwen2.5:7b)")
    p.add_argument("--seed", type=int, default=None, help="seed 고정 모드 (1회차 N, 2회차 N+1)")
    p.add_argument("--repeat", type=int, default=REPEAT_COUNT)
    p.add_argument("--strict-env", action="store_true", help="측정 환경 경고가 있으면 실행하지 않음")
    p.add_argument("--final", action="store_true", help="평가용(test·final) 문항 실행 허용 — 최종 측정 때만")
    p.add_argument("--no-guardrail", action="store_true", help="후처리 안전장치 없이 모델 원본만 기록")
    p.add_argument("--no-retry", action="store_true", help="형식 위반 응답을 다시 요청하지 않음")
    p.add_argument("--no-discard-check", action="store_true", help="폐기 직전 확인 질문을 하지 않음")
    args = p.parse_args(argv)

    blocked = check_split_guard(args.split, args.final)
    if blocked:
        print(blocked)
        return 2

    if args.method != "m0" and args.dataset != "v14":
        print("m0이 아닌 방법은 v14 평가셋에서만 실행합니다 (설계 의도 12). --dataset v14 를 함께 주세요.")
        return 2
    dataset_path, out_dir = (DATASET, OUT_DIR) if args.dataset == "v13" else (DATASET_V14, OUT_DIR_V14)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    items = select_items(dataset, args.split, args.set_name)
    if not items:
        print(f"{args.dataset} 평가셋에 {args.split}/{args.set_name} 문항이 없어 실행하지 않습니다.")
        return 2
    models = args.model or MODELS
    client = ollama.Client()

    environment = preflight_snapshot(client)
    print("=== 측정 환경 점검 ===")
    for w in environment["warnings"]:
        print(f"  ⚠️  {w}")
    if environment["warnings"] and args.strict_env:
        print("--strict-env: 측정 환경 경고가 있어 실행하지 않습니다.")
        return 2
    if not environment["warnings"]:
        print("  ✅ 경고 없음")

    seeds = None if args.seed is None else {str(i): args.seed + i - 1 for i in range(1, args.repeat + 1)}
    run_config = {
        "contract": "v2",
        "options": OPTIONS_V2,
        "repeat_count": args.repeat,
        "split": args.split,
        "set": args.set_name,
        "prompt_version": PROMPT_VERSION,
        "guardrail_version": None if args.no_guardrail else GUARDRAIL_VERSION,
        "retry_policy": None if args.no_retry else RETRY_POLICY,
        "discard_check_policy": None if args.no_discard_check else DISCARD_CHECK_POLICY,
        "system_prompt_sha256": sha256_text(SYSTEM_PROMPT_V2),
        "think": THINK,
        "method": args.method,
        "method_assets_sha256": methods.assets_sha256(args.method),
        "critical_check_policy": methods.CHECKLIST_POLICY if methods.METHODS[args.method][1] else None,
        "dataset_sha256": hashlib.sha256(json.dumps(dataset, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "item_ids": [i["id"] for i in items],
        "model_digests": get_model_digests(client, models),
        "seeds": seeds,
        "environment": environment,
    }
    total = len(models) * len(items) * args.repeat
    print(f"\n=== {len(models)}개 모델 × {len(items)}문항({args.split}/{args.set_name}) × {args.repeat}회 = {total}회 ===")

    results, warmups = [], []
    for model in models:
        unload_model(client, model)  # 설계 의도 9
        w = generate_once(client, model, SYSTEM_PROMPT_V2 + "\n[리포트]\n워밍업 입력", options_for(args.seed, 1))
        warmups.append({"model": model, "is_warmup": True, **w})
        print(f"[{model}] 워밍업 {w['elapsed_sec']}s (로드 {w['load_duration_sec']}s)")
        for run_idx in range(1, args.repeat + 1):
            opts = options_for(args.seed, run_idx)
            for n, item in enumerate(items, start=1):
                res = generate_triage(client, model, item, opts, retry=not args.no_retry,
                                      check=not args.no_discard_check, method=args.method)
                near_limit = (res.get("prompt_eval_count") or 0) + OPTIONS_V2["num_predict"] > OPTIONS_V2["num_ctx"]
                record = {
                    "eval_id": f"{model.replace(':', '_')}_{item['id']}_run{run_idx}",
                    "model": model, "run_index": run_idx, "item_id": item["id"],
                    "set": item["set"], "track": item["track"], "split": item["split"],
                    "seed": opts.get("seed"), "timestamp": datetime.now().isoformat(),
                    "hit_num_predict": res.get("eval_count", 0) >= OPTIONS_V2["num_predict"],
                    "context_near_limit": near_limit,
                    **res,
                }
                results.append(record if args.no_guardrail else apply_record(record, item))
                status = "성공" if res["success"] else f"실패 - {res['error_message']}"
                if res.get("retried"):
                    status += f" · 형식 재요청({'채택' if res['retry_adopted'] else '미채택'})"
                if res.get("critical_checked"):
                    status += f" · Critical 확인({'Critical로 올림' if res['critical_upgraded'] else '유지'})"
                if res.get("discard_checked"):
                    status += f" · 폐기 확인({'보류로 변경' if res['discard_held'] else '폐기 유지'})"
                print(f"[{model}] [Run {run_idx}] ({n}/{len(items)}) {item['id']}: {status} "
                      f"({res['elapsed_sec']}s, 입력 {res.get('prompt_eval_count')} 토큰)")
    for model in models:
        unload_model(client, model)  # 설계 의도 13

    payload = {
        "metadata": {
            "project": dataset["name"], "dataset_version": dataset["version"],
            "executed_at": datetime.now().isoformat(), "models": models,
            "total_formal_runs": len(results), "warmup_runs": len(warmups), "run_config": run_config,
        },
        "warmup_runs": warmups,
        "results": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.dataset}_{args.split}" + ("" if args.dataset == "v13" else f"_{args.method}")
    out = out_dir / f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    near = sum(r["context_near_limit"] for r in results)
    capped = sum(r["hit_num_predict"] for r in results)
    print(f"\n=== 완료: {len(results)}회 → {rel(out)}")
    fixed = [r for r in results if r.get("guardrail", {}).get("applied")]
    if not args.no_retry:
        retried = [r for r in results if r.get("retried")]
        print(f"  형식 재요청 {len(retried)}건 (채택 {sum(r['retry_adopted'] for r in retried)}건)")
    if not args.no_discard_check:
        checked = [r for r in results if r.get("discard_checked")]
        print(f"  폐기 확인 {len(checked)}건 (보류로 변경 {sum(r['discard_held'] for r in checked)}건)")
    crit_checked = [r for r in results if r.get("critical_checked")]
    if crit_checked:
        print(f"  Critical 확인 {len(crit_checked)}건 (Critical로 올림 {sum(r['critical_upgraded'] for r in crit_checked)}건)")
    if not args.no_guardrail:
        print(f"  후처리 안전장치({GUARDRAIL_VERSION}) 적용 {len(fixed)}건")
    if near:
        print(f"  ⚠️  입력+출력 상한이 num_ctx 를 넘을 수 있는 회차 {near}건 — 프롬프트 길이를 확인하세요")
    if capped:
        print(f"  ⚠️  출력이 num_predict({OPTIONS_V2['num_predict']}) 상한에 걸린 회차 {capped}건")
    print("채점: uv run triage-score")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
