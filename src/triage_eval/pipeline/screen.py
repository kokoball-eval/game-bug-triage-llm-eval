"""후보 모델 사전 점검 (v1.4 1단계) — 측정하기 전에 "이 모델로 측정해도 되는가"를 확인한다.

사용법:
    ollama pull <후보 모델>                         # 먼저 받아 둔다
    uv run triage-screen --strict-env            # 기본: 현재 선정 모델 + 후보 6개
    uv run triage-screen --model gemma4:12b      # 모델 하나만

출력:
    data/results/v14/screening/screening_<시각>.json   점검 기록 (항상 새 파일)

점검 항목 (모델별, 하나라도 FAIL이면 2단계 측정 대상에서 뺀다)
------------------------------------------------------------
    C1 설치        ollama list 에 있고 digest 를 읽을 수 있음
    C2 생각 끄기   think=False 로 불렀을 때 생각 과정이 응답에 섞이지 않음
    C3 GPU 적재    num_ctx 8192 로 올렸을 때 모델 전체가 VRAM에 들어감 (CPU로 넘친 부분 0)
    C4 구조화 출력 선택지 스키마(enum)와 허용 문자 스키마(pattern) 응답이 JSON으로 읽히고 제한 안에 있음
    C5 출력 형식   개발용 3건의 응답에서 필드 누락(R2)·출력 언어 위반(R7)이 없음
    참고 기록      라이선스 첫 줄, 기본 상태에서 생각 과정을 출력하는지, think 인자를 받는지, 지연

[설계 의도]
1. 평가용(test) 문항은 쓰지 않는다. 개발용 문항만 고르고, 고른 문항에 평가용이 섞이면 실행하지 않는다.
   평가용 세트로 모델을 고르면 평가용이 "모델 선택용 연습 문제"가 되어, 마지막 확인에 쓸 수 없게 된다
   (머신러닝 과정의 봉인 Test 원칙, 프롬프트 엔지니어링 과정의 개발/최종 데이터 분리).
2. 이 점검은 성능 측정이 아니다. 3건의 정답률은 계산하지도 기록하지도 않는다. 3건 점수로 후보를 거르면
   개발용 3건에 맞춘 선택이 되고, 표본이 작아 우연에 좌우된다. 여기서는 "측정할 수 있는 상태인가"만 가린다.
3. 모든 모델을 같은 조건으로 부른다 — 같은 문항, 같은 프롬프트(v2.3), 같은 생성 옵션(OPTIONS_V2), 같은 seed.
   후보마다 조건이 다르면 차이가 모델 때문인지 조건 때문인지 알 수 없다
   (머신러닝 과정의 공정한 비교 계약, 프롬프트 엔지니어링 과정의 변수 통제).
4. 모델을 바꿀 때마다 앞 모델을 내린다(keep_alive=0). 앞 모델이 VRAM에 남아 있으면 다음 모델의 GPU 적재
   판정이 틀어지고, 이전 상태가 응답에 섞일 수 있다(docs/issue_log.md OBS-002).
5. 현재 선정 모델(qwen2.5:7b)도 함께 점검한다. 생각 기능이 없는 모델에 think=False 를 보내도 되는지 확인하는
   대조군이다. 이 결과로 2단계에서 run.py 가 think 인자를 어떻게 넘길지 정한다. 이 파일은 run.py 를 바꾸지 않는다.
6. 판정 로직(judge_*)은 순수 함수로 두고, Ollama 호출은 screen_model() 한 곳에 모은다.
   가짜 클라이언트로 판정 로직을 모델 없이 테스트할 수 있다 (preflight.py 와 같은 구조).
7. 사람이 판단할 항목은 PASS/FAIL로 정하지 않고 기록만 한다. 라이선스 조건은 문구를 읽고 사람이 정한다.
8. C3는 ollama ps 의 값을 그대로 믿지 않는다. 첫 점검(2026-10-02)에서 gemma4:12b 의 적재 크기가 896 MiB로
   보고되어(모델 파일 7.4 GB) GPU 적재 PASS가 났지만, 평균 지연이 현재 모델의 3배였다. 측정값이 상식 범위
   (모델 파일 크기의 90% 이상) 밖이면 PASS/FAIL 대신 판정 불가(HOLD)로 두고, 원본 ps 값을 기록에 남긴다.
   측정 도구가 틀린 값으로 PASS를 내는 것이 측정을 못 하는 것보다 위험하다. 판정 불가가 나오면 사람이
   Ollama 밖의 측정값으로 확인한다. 그 근거로 쓰도록 적재 직후 nvidia-smi VRAM 사용량과 생성 속도(tok/s)를 함께 기록한다
   (같은 날 확인: gemma4:12b 는 ps 939 MB / nvidia-smi 6,750 MiB / 29.4 tok/s, qwen2.5:7b 는 5.0 GB / 4,876 MiB / 70.9 tok/s).
"""

import argparse
import json
import re
import time
from datetime import datetime

import ollama

from triage_eval.common.ollama_runtime import get_model_digests
from triage_eval.common.paths import ROOT
from triage_eval.common.preflight import gpu_used_mib
from triage_eval.common.preflight import snapshot as preflight_snapshot
from triage_eval.pipeline.contract import FORBIDDEN_SCRIPTS, LINE_PATTERNS, OUTPUT_LANG, ENUMS_V2, score_format_v2
from triage_eval.pipeline.prompt import PROMPT_VERSION, build_prompt
from triage_eval.pipeline.run import DATASET, OPTIONS_V2, retry_schema

OUT_DIR = ROOT / "data" / "results" / "v14" / "screening"
CURRENT_MODEL = "qwen2.5:7b"
# 후보 선정 근거는 v1.4 보고서 "후보 선정" 절 — 한국어 지원, 8GB VRAM, 상업적 이용 가능 라이선스, Ollama 공식 라이브러리
CANDIDATES = ["qwen3.5:9b", "gemma4:e4b", "gemma4:12b", "qwen3:8b", "granite4:tiny-h", "qwen3.5:4b"]
SEED = 1
THINK_MARKERS = re.compile(r"<think>|</think>|<\|think\|>|<thinking>", re.I)


# ── 판정 로직 (순수 함수, 설계 의도 6) ─────────────────────────────

def pick_items(dataset: dict) -> list[dict]:
    """개발용에서 트랙 A·트랙 B·집중 세트 첫 문항을 하나씩 고른다 (설계 의도 1)."""
    dev = [i for i in dataset["items"] if i["split"] == "dev"]
    picks = [next((i for i in dev if i["set"] == "representative" and i["track"] == "A"), None),
             next((i for i in dev if i["set"] == "representative" and i["track"] == "B"), None),
             next((i for i in dev if i["set"] == "focused"), None)]
    if any(i is None or i["split"] != "dev" for i in picks):  # 개발용이 모자라도 평가용으로 채우지 않는다
        raise RuntimeError("개발용 문항으로 점검 대상을 채울 수 없어 중단합니다.")
    return picks


def judge_thinking(response_text: str, thinking_text: str | None) -> tuple[bool, str]:
    """C2 — 응답 본문에 생각 표지가 없고, 별도 생각 필드도 비어 있으면 통과."""
    if thinking_text and thinking_text.strip():
        return False, f"생각 과정 {len(thinking_text)}자가 출력됨"
    if THINK_MARKERS.search(response_text or ""):
        return False, "응답 본문에 생각 표지가 있음"
    return True, ""


def judge_gpu(ps_entry: dict | None, disk_bytes: int | None = None) -> tuple[bool | None, str]:
    """C3 — size_vram 이 size 와 같으면 전량 GPU 적재. 정보를 못 읽으면 None(판정 불가).
    ps 가 보고한 적재 크기가 모델 파일 크기보다 작으면 값 자체를 믿을 수 없으므로 판정하지 않는다(설계 의도 8)."""
    if not ps_entry or not ps_entry.get("size"):
        return None, "ollama ps 에서 모델 정보를 읽지 못함"
    size, vram = ps_entry["size"], ps_entry.get("size_vram", 0)
    if disk_bytes and size < disk_bytes * 0.9:
        return None, (f"ps 적재 크기 {round(size / 2**20)} MiB < 모델 파일 {round(disk_bytes / 2**20)} MiB — "
                      "값을 믿을 수 없어 판정 불가, ollama ps 의 PROCESSOR 칸으로 직접 확인 필요")
    cpu_mib = round((size - vram) / 2**20)
    if cpu_mib > 0:
        return False, f"CPU로 넘친 부분 {cpu_mib} MiB (전체 {round(size / 2**20)} MiB)"
    return True, f"전체 {round(size / 2**20)} MiB GPU 적재"


def judge_enum_json(text: str, fields: list[str]) -> tuple[bool, str]:
    """C4(enum) — JSON으로 읽히고 각 필드 값이 허용 값 안인가."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False, f"JSON으로 읽을 수 없음: {str(text)[:60]!r}"
    bad = [f"{f}={data.get(f)!r}" for f in fields if data.get(f) not in ENUMS_V2[f]]
    return (not bad), ("허용 값 밖: " + ", ".join(bad)) if bad else ""


def judge_pattern_json(text: str, field: str, lang: str = OUTPUT_LANG) -> tuple[bool, str]:
    """C4(pattern) — JSON으로 읽히고 값이 허용 문자 패턴에 맞는가."""
    try:
        value = json.loads(text).get(field, "")
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False, f"JSON으로 읽을 수 없음: {str(text)[:60]!r}"
    if not isinstance(value, str) or not re.fullmatch(LINE_PATTERNS[lang], value) or FORBIDDEN_SCRIPTS[lang].search(value):
        return False, f"허용 문자 밖: {str(value)[:40]!r}"
    return True, ""


def judge_format(texts: list[str]) -> tuple[bool, str]:
    """C5 — 필드 누락(R2)·출력 언어 위반(R7)이 한 건도 없으면 통과. 다른 형식 규칙은 참고로만 센다."""
    rules = [score_format_v2(t)["rules"] for t in texts]
    r2 = sum(not r["R2_all_fields"] for r in rules)
    r7 = sum(not r["R7_output_language"] for r in rules)
    others = {k: sum(not r[k] for r in rules) for k in rules[0] if k not in ("R2_all_fields", "R7_output_language")}
    note = f"R2 위반 {r2}건, R7 위반 {r7}건 / 참고: " + ", ".join(f"{k.split('_')[0]} {v}" for k, v in others.items())
    return (r2 == 0 and r7 == 0), note


def overall(checks: dict) -> str:
    """하나라도 False면 FAIL, 판정 불가(None)가 있으면 HOLD, 모두 True면 PASS."""
    values = [c["pass"] for c in checks.values()]
    if any(v is False for v in values):
        return "FAIL"
    return "HOLD" if any(v is None for v in values) else "PASS"


# ── Ollama 호출 (설계 의도 6) ───────────────────────────────────────

def call(client, model: str, prompt: str, options: dict, think, schema: dict | None = None) -> dict:
    """1회 생성. think 를 거부하는 모델이면 그 사실을 남기고 think 없이 다시 부른다."""
    kwargs = {"format": schema} if schema else {}
    start = time.perf_counter()
    think_rejected = False
    try:
        r = client.generate(model=model, prompt=prompt, options=options, think=think, **kwargs)
    except Exception as e:  # 생각 기능이 없는 모델은 think 인자를 거부할 수 있다 (설계 의도 5)
        if think is None or "think" not in str(e).lower():
            return {"ok": False, "error": str(e), "elapsed_sec": round(time.perf_counter() - start, 3)}
        think_rejected = True
        r = client.generate(model=model, prompt=prompt, options=options, **kwargs)
    eval_ns = r.get("eval_duration") or 0
    return {"ok": True, "text": (r.get("response") or "").strip(), "thinking": r.get("thinking"),
            "think_rejected": think_rejected, "elapsed_sec": round(time.perf_counter() - start, 3),
            "tokens_per_sec": round(r.get("eval_count", 0) / (eval_ns / 1e9), 1) if eval_ns > 0 else None}


def unload(client, model: str) -> None:
    """설계 의도 4 — 모델을 VRAM에서 내린다. 실패해도 점검은 계속한다."""
    try:
        client.generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def disk_size(client, model: str) -> int | None:
    """ollama list 의 모델 파일 크기(바이트). C3 판정값의 상식 검사에 쓴다 (설계 의도 8)."""
    try:
        for m in client.list().get("models", []):
            if (m.get("model") or m.get("name")) == model:
                return m.get("size") or None
    except Exception:
        pass
    return None


def ps_entry(client, model: str) -> dict | None:
    """ollama ps 에서 이 모델(정확히 같은 이름)의 적재 정보."""
    try:
        for m in client.ps().get("models", []):
            if (m.get("model") or m.get("name")) == model:
                return {"size": m.get("size", 0), "size_vram": m.get("size_vram", 0),
                        "context_length": m.get("context_length")}
    except Exception:
        pass
    return None


def show_info(client, model: str) -> dict:
    try:
        s = client.show(model)
        lic = (s.get("license") or "").strip().splitlines()
        return {"capabilities": list(s.get("capabilities") or []), "license_first_line": lic[0][:120] if lic else None}
    except Exception as e:
        return {"capabilities": None, "license_first_line": None, "error": str(e)}


def screen_model(client, model: str, items: list[dict], digest: str | None, disk_bytes: int | None = None) -> dict:
    checks = {"C1_installed": {"pass": bool(digest), "note": "" if digest else "ollama pull 이 필요함"}}
    if not digest:
        return {"model": model, "result": "FAIL", "checks": checks}
    unload(client, model)
    options = {**OPTIONS_V2, "seed": SEED}
    info = show_info(client, model)

    # 기본 상태(think 미지정)에서 생각 과정을 출력하는지 — 참고 기록
    default = call(client, model, build_prompt(items[0]), options, think=None)
    ps = ps_entry(client, model)
    gpu = judge_gpu(ps, disk_bytes)
    vram_used = gpu_used_mib()  # Ollama 계산과 무관한 드라이버 측정값 (설계 의도 8, 참고 기록)
    default_thinks = (not judge_thinking(default.get("text", ""), default.get("thinking"))[0]) if default["ok"] else None

    # think=False 로 개발용 3건
    runs = [call(client, model, build_prompt(i), options, think=False) for i in items]
    failed = [r["error"] for r in runs if not r["ok"]]
    if failed:
        checks["C2_think_off"] = {"pass": False, "note": f"호출 실패: {failed[0][:80]}"}
    else:
        bad = [judge_thinking(r["text"], r["thinking"]) for r in runs]
        notes = [n for ok, n in bad if not ok]
        checks["C2_think_off"] = {"pass": not notes, "note": notes[0] if notes else ""}
    checks["C3_gpu_fit"] = {"pass": gpu[0], "note": gpu[1]}

    enum_fields = ["분류", "우선순위"]
    e = call(client, model, build_prompt(items[0]), options, think=False, schema=retry_schema(enum_fields))
    p = call(client, model, build_prompt(items[0]), options, think=False, schema=retry_schema(["요약"]))
    e_ok = judge_enum_json(e["text"], enum_fields) if e["ok"] else (False, f"호출 실패: {e['error'][:80]}")
    p_ok = judge_pattern_json(p["text"], "요약") if p["ok"] else (False, f"pattern 호출 실패: {p['error'][:80]}")
    checks["C4_structured"] = {"pass": e_ok[0] and p_ok[0], "note": " / ".join(n for n in (e_ok[1], p_ok[1]) if n)}

    texts = [r["text"] for r in runs if r["ok"]]
    fmt = judge_format(texts) if texts else (False, "응답 없음")
    checks["C5_format"] = {"pass": fmt[0], "note": fmt[1]}
    unload(client, model)

    ok_runs = [r for r in runs if r["ok"]]
    return {
        "model": model, "digest": digest, "result": overall(checks), "checks": checks,
        "info": {**info, "ps_raw": ps, "disk_bytes": disk_bytes, "vram_used_mib_after_load": vram_used,
                 "default_outputs_thinking": default_thinks,
                 "think_param_rejected": any(r.get("think_rejected") for r in ok_runs),
                 "avg_elapsed_sec": round(sum(r["elapsed_sec"] for r in ok_runs) / len(ok_runs), 3) if ok_runs else None,
                 "avg_tokens_per_sec": (round(sum(r["tokens_per_sec"] for r in ok_runs if r["tokens_per_sec"])
                                              / len([r for r in ok_runs if r["tokens_per_sec"]]), 1)
                                        if any(r["tokens_per_sec"] for r in ok_runs) else None)},
        "responses": [{"id": i["id"], "text": r.get("text", ""), "thinking": r.get("thinking")} for i, r in zip(items, runs)],
        "structured": {"enum": e.get("text"), "pattern": p.get("text")},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="v1.4 후보 모델 사전 점검 (측정 아님)")
    ap.add_argument("--model", action="append", help="점검할 모델 (여러 번 지정 가능, 기본: 현재 모델 + 후보 6개)")
    ap.add_argument("--strict-env", action="store_true", help="측정 환경 경고가 있으면 실행하지 않음")
    args = ap.parse_args(argv)
    models = args.model or [CURRENT_MODEL, *CANDIDATES]

    client = ollama.Client()
    env = preflight_snapshot(client)
    if env["warnings"]:
        print("측정 환경 경고: " + "; ".join(env["warnings"]))
        if args.strict_env:
            print("--strict-env: 측정 환경 경고가 있어 실행하지 않습니다.")
            return 2
    items = pick_items(json.loads(DATASET.read_text(encoding="utf-8")))
    digests = get_model_digests(client, models)

    print(f"사전 점검 대상: {', '.join(models)} / 문항: {', '.join(i['id'] for i in items)} (개발용)\n")
    results = []
    for m in models:
        print(f"[{m}] 점검 중...")
        res = screen_model(client, m, items, digests.get(m), disk_size(client, m))
        results.append(res)
        for name, c in res["checks"].items():
            mark = {True: "PASS", False: "FAIL", None: "HOLD"}[c["pass"]]
            print(f"  {name:<14} {mark:<4} {c['note']}")
        info = res.get("info", {})
        if info:
            print(f"  참고: 기본 상태 생각 출력={info['default_outputs_thinking']}, think 거부={info['think_param_rejected']}, "
                  f"평균 {info['avg_elapsed_sec']}초 · {info['avg_tokens_per_sec']} tok/s, 적재 후 VRAM {info['vram_used_mib_after_load']} MiB, "
                  f"기능={info['capabilities']}")
            print(f"        라이선스: {info['license_first_line']}")
        print(f"  → {res['result']}\n")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"screening_{datetime.now():%Y%m%d_%H%M%S}.json"
    record = {"kind": "model_screening", "created": datetime.now().isoformat(timespec="seconds"),
              "prompt_version": PROMPT_VERSION, "options": {**OPTIONS_V2, "seed": SEED},
              "items": [i["id"] for i in items], "environment": env, "results": results}
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print("요약: " + ", ".join(f"{r['model']} {r['result']}" for r in results))
    print(f"기록: {out.relative_to(ROOT).as_posix()}")
    return 0 if all(r["result"] == "PASS" for r in results if r["model"] != CURRENT_MODEL) else 1


if __name__ == "__main__":
    raise SystemExit(main())
