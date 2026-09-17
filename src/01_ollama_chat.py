"""단일 호출 스모크 테스트 (1일차).

본 실험(40회) 전에 모델이 실제로 적재·응답하는지, 기본 출력 성향이 어떤지를
모델당 1회 호출로 먼저 확인한다. 워밍업을 분리하지 않은 콜드 스타트 측정이므로
소요 시간에 모델 로딩 시간이 포함된다. 본 실험 수치와 같은 선상에서 비교하지 않는다.

MODEL_TAG를 바꿔 모델별로 각각 1회씩 실행한다.

출력:
    data/results/<모델태그>_verify.json

주의: 재실행하면 기존 1일차 검증 로그를 덮어쓴다.
보고서가 이 로그의 값을 인용하고 있으므로, 기록을 보존하려면 실행 전 백업할 것.
"""

import json
import time
from pathlib import Path
import ollama

# 테스트할 모델 태그를 변경해주는 곳 
# (후보 1: "qwen2.5:7b", 후보 2: "llama3.1:8b")
MODEL_TAG = "llama3.1:8b"

# QA 실무 단일 테스트 프롬프트를 변경해주는 곳
TEST_PROMPT = """
다음 인게임 버그 리포트를 분석하여 아래 규격에 맞게 3줄로 요약하세요.
1. 결함 카테고리 (Crash/Freeze, Balance, UI/Graphic, Quest 중 택1)
2. 심각도 (Blocker, Critical, Major, Minor 중 택1)
3. 1줄 요약

[리포트 내용]
스피릿 아일랜드 보스 레이드 3페이즈 진입 컷씬에서 파티원 전원의 클라이언트가 비정상 종료(튕김)됩니다. 
재접속 시도 시 캐릭터가 던전 외부로 튕겨나가며 레이드 티켓이 복구되지 않습니다.
""".strip()

def run_single_eval(model: str, prompt: str) -> dict:
    client = ollama.Client()

    # 응답 시간 측정 시작
    start_time = time.perf_counter()
    response = client.generate(
        model=model,
        prompt=prompt,
        options={
            "temperature": 0.2,  # 일관된 트리아지 분류를 위해 낮게 설정
            "num_predict": 300,
        }
    )
    elapsed_sec = time.perf_counter() - start_time

    # [수정 포인트 1] 추론 직후 VRAM 점유량 확인 (모델 적재 완료 시점)
    ps_after = client.ps()
    vram_bytes = 0
    for m in ps_after.get("models", []):
        # 모델 태그가 부분 일치하거나 일치하는 경우 VRAM 크기 추출
        name = m.get("name", "")
        if name == model or name.startswith(model.split(":")[0]):
            vram_bytes = m.get("size_vram", 0)
            break

    # 성능 지표 파싱
    load_duration_sec = response.get("load_duration", 0) / 1_000_000_000
    eval_duration_ns = response.get("eval_duration", 0)
    eval_count = response.get("eval_count", 0)
    
    # eval_duration이 유효할 때만 tokens/s 계산 (결측 시 None)
    tokens_per_sec = (
        round(eval_count / (eval_duration_ns / 1_000_000_000), 2)
        if eval_duration_ns > 0
        else None
    )

    result_data = {
        "model": model,
        "prompt": prompt,
        "response_text": response.get("response", "").strip(),
        "elapsed_sec": round(elapsed_sec, 3),
        "load_duration_sec": round(load_duration_sec, 3),
        "eval_count": eval_count,
        "tokens_per_sec": tokens_per_sec,
        "vram_mib": round(vram_bytes / (1024 * 1024), 2),
    }
    return result_data

if __name__ == "__main__":
    print(f"[{MODEL_TAG}] 모델 테스트 실행 중...")
    result = run_single_eval(MODEL_TAG, TEST_PROMPT)
    
    # 콘솔 출력
    print("\n--- [추론 결과] ---")
    print(result["response_text"])
    print("\n--- [성능 메타데이터] ---")
    print(f"소요 시간: {result['elapsed_sec']}초 | 로딩 시간: {result['load_duration_sec']}초")
    print(f"토큰 생성 속도: {result['tokens_per_sec']} tokens/s | VRAM: {result['vram_mib']} MiB")

    # [수정 포인트 2] data/results 디렉토리에 모델명 기반으로 분리 저장
    output_dir = Path("data/results")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 태그에서 콜론(:)을 언더바(_)로 치환하여 파일명 생성 (예: qwen2.5_7b_verify.json)
    safe_model_name = MODEL_TAG.replace(":", "_")
    output_path = output_dir / f"{safe_model_name}_verify.json"
    
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        
    print(f"\n결과 저장 완료: {output_path.resolve()}")