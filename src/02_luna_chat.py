import json
import os
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path
from openai import OpenAI

MODEL_NAME = "gpt-5.6-luna"

SYSTEM_PROMPT = """당신은 8년 차 게임 QA 엔지니어의 버그 리포트 1차 트리아지 어시스턴트입니다.
제시된 버그 리포트를 엄격하게 분석하여 반드시 아래 5개 필드 규격만 사용하여 작성하세요. 서두나 사족은 절대 출력하지 마세요.

[요약]: 결함 현상 1줄 요약
[모듈]: 전투, 결제, UI, 그래픽, 시스템, 네트워크 등 중 택1 (복합 이슈 시 병기)
[심각도]: Blocker, Critical, Major, Minor, Trivial, 판단보류 중 택1
[재현 여부]: 발생(100%), 간헐적, 불명확, 재현 불가 중 택1
[누락 정보 및 권장 조치]: 추가 확인이 필요한 기기/OS/재현스텝 또는 QA 권장 조치
"""

def get_api_client() -> OpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        api_key = getpass("OpenAI API 키를 입력하세요 (화면에 보이지 않음): ").strip()
    return OpenAI(api_key=api_key)

def execute_cloud_inference(client: OpenAI, report_text: str) -> dict:
    full_prompt = f"{SYSTEM_PROMPT}\n\n[버그 리포트]\n{report_text}"
    start_time = time.perf_counter()
    
    try:
        response = client.responses.create(
            model=MODEL_NAME,
            input=full_prompt,
        )
        elapsed_sec = round(time.perf_counter() - start_time, 3)

        # 토큰 사용량 파싱
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", 0) if usage else (input_tokens + output_tokens)

        return {
            "success": True,
            "response_text": response.output_text.strip(),
            "elapsed_sec": elapsed_sec,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "error_message": None,
        }
    except Exception as e:
        elapsed_sec = round(time.perf_counter() - start_time, 3)
        return {
            "success": False,
            "response_text": "",
            "elapsed_sec": elapsed_sec,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "error_message": str(e),
        }

def main():
    root_dir = Path(__file__).resolve().parent.parent
    data_path = root_dir / "data" / "questions.json"
    results_dir = root_dir / "data" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    with data_path.open("r", encoding="utf-8") as f:
        questions_data = json.load(f)

    # cloud_eval이 true인 문항만 필터링 (사전 선정 5건: Q01, Q02, Q06, Q08, Q10)
    cloud_questions = [q for q in questions_data["questions"] if q.get("cloud_eval") is True]

    print(f"=== Cloud API ({MODEL_NAME}) 비교 실험 시작: 총 {len(cloud_questions)}문항 × 1회 ===")
    client = get_api_client()

    cloud_records = []

    for idx, q in enumerate(cloud_questions, start=1):
        q_id = q["id"]
        print(f"[{MODEL_NAME}] ({idx}/{len(cloud_questions)}) {q_id}: {q['title'][:25]}... ", end="", flush=True)

        res = execute_cloud_inference(client, q["report_text"])

        record = {
            "eval_id": f"cloud_luna_{q_id}",
            "model": MODEL_NAME,
            "model_type": "cloud_api",
            "question_id": q_id,
            "question_type": q["type"],
            "run_index": 1,
            "timestamp": datetime.now().isoformat(),
            **res,
        }
        cloud_records.append(record)

        if res["success"]:
            print(f"성공 ({res['elapsed_sec']}s, In:{res['input_tokens']} / Out:{res['output_tokens']} tokens)")
        else:
            print(f"실패 - 사유: {res['error_message']}")

    output_payload = {
        "metadata": {
            "project": questions_data.get("project", "Aether Raid Bug Triage"),
            "model": MODEL_NAME,
            "executed_at": datetime.now().isoformat(),
            "sample_size": len(cloud_records),
            "note": "Cloud API는 공통 질문 5건에 대해 1회 실행 (로컬 2회 반복과 n 차이 명시)",
        },
        "results": cloud_records,
    }

    output_file = results_dir / "cloud_eval_results.json"
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    print(f"\n=== Cloud API 실험 완료 ===")
    print(f"결과 저장 위치: {output_file.resolve()}")

if __name__ == "__main__":
    main()