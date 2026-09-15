"""
4일차 Few-Shot 가드레일 교정 검증 스크립트

목적
----
2일차 본 실험에서 Qwen2.5-7B가 단문 리포트(Q08: "크래시남")에 대해
`[누락 정보 및 권장 조치]: 없음` 으로 소극 처리한 결함을, 시스템 프롬프트에
단문 대응 Few-Shot 예시 1건을 주입해 교정할 수 있는지 확인한다.

기대 결과
--------
[심각도] 판단보류 / [재현 여부] 불명확 판정과 함께
기기 모델명·OS 버전·재현 스텝을 역질문해야 한다.

주의
----
본 스크립트는 40회 본 실험과 별개의 보완 검증이며, 본 실험 집계에 합산하지 않는다.
모델·프롬프트·생성 설정은 4일차 검증 당시와 동일하게 유지한다.

사용법
------
    uv run python src/test_fewshot.py

출력
----
    data/results/fewshot_verify.json   : 응답 원문 및 판정 근거 (재판독 가능 형식)
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import ollama

MODEL = "qwen2.5:7b"
OPTIONS = {"temperature": 0.2}

system_prompt = """당신은 게임 'Aether Raid'의 전문 QA 엔지니어입니다.
인입된 인게임 버그 리포트를 분석하여 아래 5개 고정 필드 규격에 맞춰 트리아지 결과를 작성하세요.

[출력 제약 사항]
1. 사족이나 인사말은 절대 출력하지 마십시오.
2. 반드시 첫 번째 필드인 '[요약]:'으로 즉시 출력을 시작하십시오.
3. 없는 사실을 지어내지(환각) 마십시오.
4. 정보가 부족한 단문 리포트의 경우, [심각도]는 '판단보류', [재현 여부]는 '불명확'으로 처리하고 추가 정보(기기, OS, 재현스텝)를 역질문하십시오.

[출력 필드 규격]
[요약]: 결함 현상 1줄 핵심 요약
[모듈]: 결함 발생 영역 (전투, 결제, UI, 그래픽, 시스템 등)
[심각도]: Blocker, Critical, Major, Minor, Trivial, 판단보류 중 택1
[재현 여부]: 발생(100%), 간헐적, 발생(특정 기기), 불명확 중 택1
[누락 정보 및 권장 조치]: 추가 확인이 필요한 기기/OS/계정 정보 및 QA 권장 사항

[Few-Shot 예시]
입력: 튕김
출력:
[요약]: 앱 강제 종료(크래시) 현상 제보
[모듈]: 시스템
[심각도]: 판단보류
[재현 여부]: 불명확
[누락 정보 및 권장 조치]: 튕김 발생 시점, 사용 기기 모델명, OS 버전의 추가 인입이 필요하며 재현 스텝 확보 후 재분류 권장."""

user_input = """다음 버그 리포트를 분석하세요:

[리포트 내용]
크래시남"""


def evaluate(text: str) -> dict:
    """교정 성공 여부를 기계적으로 판정한다 (수작업 눈대중 대신 근거를 남기기 위함)."""
    def field(name: str) -> str:
        m = re.search(rf"^\[{re.escape(name)}\]\s*:\s*(.*)$", text, re.MULTILINE)
        return m.group(1).strip() if m else ""

    severity = field("심각도")
    repro = field("재현 여부")
    missing = field("누락 정보 및 권장 조치")

    asked_keywords = [k for k in ("기기", "OS", "재현", "버전", "단말") if k in missing]
    checks = {
        "심각도_판단보류": severity == "판단보류",
        "재현여부_불명확": repro == "불명확",
        "누락정보_역질문_수행": bool(missing) and missing not in ("없음", "없음.") and len(asked_keywords) >= 2,
        "서두_사족_없음": text.strip().startswith("[요약]"),
    }
    return {
        "parsed_fields": {"심각도": severity, "재현 여부": repro, "누락 정보 및 권장 조치": missing},
        "requested_info_keywords": asked_keywords,
        "checks": checks,
        "corrected": all(checks.values()),
    }


def main():
    root = Path(__file__).resolve().parent.parent

    print(f"[{MODEL}] 4일차 Few-Shot 교정 검증 실행 중...")
    start = time.perf_counter()
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        options=OPTIONS,
    )
    elapsed = round(time.perf_counter() - start, 3)

    text = response["message"]["content"].strip()
    print("\n--- [응답] ---")
    print(text)

    verdict = evaluate(text)
    print("\n--- [판정] ---")
    for k, v in verdict["checks"].items():
        print(f"  {'✅' if v else '❌'} {k}")
    print(f"\n교정 성공 여부: {'성공' if verdict['corrected'] else '미교정'}")

    payload = {
        "experiment": "4일차 Few-Shot 단문 대응 교정 검증",
        "note": "40회 본 실험과 별개의 보완 검증이며 본 실험 집계에 합산하지 않음",
        "executed_at": datetime.now().isoformat(),
        "model": MODEL,
        "options": OPTIONS,
        "baseline_reference": {
            "question_id": "Q08",
            "baseline_issue": "본 실험(가드레일 미적용)에서 Qwen2.5-7B가 '[누락 정보 및 권장 조치]: 없음'으로 소극 처리",
            "baseline_log": "data/results/local_eval_results.json (qwen2.5_7b_Q08_run1)",
        },
        "system_prompt": system_prompt,
        "user_input": user_input,
        "elapsed_sec": elapsed,
        "response_text": text,
        "verdict": verdict,
    }

    out = root / "data" / "results" / "fewshot_verify.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장 완료: {out}")


if __name__ == "__main__":
    main()
