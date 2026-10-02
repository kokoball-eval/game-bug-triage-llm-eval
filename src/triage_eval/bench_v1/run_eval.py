"""40회 로컬 벤치마크 본 실험 스크립트 (2일차).

두 후보 모델에 동일한 조건으로 고정 질문 10건을 2회씩 실행하고,
응답 원문과 성능 메타데이터를 원본 로그로 남긴다.

    10문항 x 2모델 x 2회 = 40회 (+ 모델별 워밍업 1회는 별도 집계)

사용법:
    uv run bench-run                  # 이력만 저장 (기본)
    uv run bench-run --seed 1         # (v1.2) seed 고정 모드: 1회차 seed=1, 2회차 seed=2
    uv run bench-run --strict-env     # (v1.2) 측정 환경 경고가 있으면 실행하지 않음
    uv run bench-run --update-latest  # 이력 저장 + 문서 기준 파일도 교체

출력:
    data/results/history/local_eval_results_<시각>.json - 실행 기록 (항상 저장)
    data/results/local_eval_results.json              - 문서 수치의 출처. --update-latest 일 때만 교체

[설계 의도]
1. chat()이 아니라 generate() + 문자열 결합을 쓴다.
   chat()은 모델별 chat 템플릿에 맞춰 messages를 조립하므로, 같은 messages를 넣어도
   지시문이 놓이는 위치와 구분자가 모델마다 달라진다.
   직접 조립해, 통제 대상인 부분(시스템 지시문 + 리포트 본문)이
   두 모델에 같은 순서, 같은 글자로 들어가도록 고정했다.
   단, generate()도 raw=True를 주지 않으면 모델 고유 템플릿은 그대로 적용된다.
   그 포장까지 제거하지는 않았다. 각 모델의 정상 동작이며, 제거하면 오히려 왜곡이다.
2. 워밍업 1회를 먼저 돌리고 warmup_runs 키에 분리 저장한다.
   첫 호출에는 디스크->VRAM 적재 시간이 붙으므로 본 통계에 섞으면 안 된다.
   단, 로딩 시간 자체는 별도 지표로 보고한다.
3. eval_duration이 0 이하이면 tokens_per_sec를 None으로 둔다. 0으로 대체하지 않는다.
   계산 불가를 0으로 채우면 "속도가 0이었다"는 뜻이 되어 평균이 무너진다.
4. 예외는 잡아서 success=False로 기록하고 다음 회차로 진행한다.
   한 건의 실패로 40회 배치가 중단되지 않게 하고, 실패 사유를 로그에 남긴다.
5. 생성 파라미터는 파일 상단 OPTIONS 상수 하나로 둔다.
   두 모델에 동일한 값이 적용됨을 코드로 보장하기 위해서다.
6. 결과는 metadata + warmup_runs + results 구조로 저장한다.
   집계된 숫자가 아니라 회차별 원본을 남겨야 사후 재집계와 재검증이 가능하다.
7. (v1.1) metadata.run_config 에 실행 조건을 기록한다.
   생성 옵션, 반복 횟수, 시스템 프롬프트·문항 파일의 SHA-256 지문, 모델 digest.
   compare_runs.py 가 두 실행을 비교하기 전에 "같은 조건에서 돌린 것인가"를 코드로 확인하기 위해서다.
   프롬프트 전문 대신 지문(해시)을 남기는 이유: 한 글자만 바뀌어도 값이 달라져 변경 여부를 확실히 잡고,
   로그 크기는 늘지 않는다. 실험 동작(모델 호출 방식·옵션)은 바꾸지 않는다.
8. (v1.1.1) 기본 실행은 history/ 에만 저장하고 local_eval_results.json 은 건드리지 않는다.
   이 파일은 README·보고서 수치의 출처라서, 재실행 한 번에 덮어써지면
   summarize_eval.py 결과가 문서와 어긋난다(2026-09-30 재실행에서 실제로 발생).
   새 결과를 문서 기준으로 삼기로 "결정"했을 때만 --update-latest 로 교체한다.
9. (v1.2) --seed N 을 주면 회차마다 다른 고정 seed 를 쓴다 (1회차 N, 2회차 N+1).
   회차마다 seed 를 다르게 두는 이유: 같은 seed 로 두 번 돌리면 "출력 안정성 관찰"이라는
   2회 반복 설계의 의미가 사라진다. 회차별로 다르되 고정된 seed 를 쓰면, 회차 간 변동은 관찰하면서도
   같은 명령을 다시 실행했을 때 같은 결과가 나와야 한다(재현성).
   seed 는 run_config.seeds 에 남고, compare_runs.py 는 두 실행의 seeds 가 같을 때만
   판정 변화를 합격 기준으로 쓴다. 기본 OPTIONS 는 그대로 두므로 seed 없는 실행과도 비교할 수 있다.
10. (v1.2) 모델 호출 전에 측정 환경(GPU 점유·Ollama 적재 모델·전원)을 점검해 run_config.environment 에
   남긴다(src/triage_eval/common/preflight.py). 경고가 있어도 기본은 계속 진행하고, --strict-env 일 때만 멈춘다.

[Context 설정 관련 주의]
본 40회 실험은 num_ctx를 명시하지 않고 Ollama 기본값 그대로 실행되었다.
`src/triage_eval/bench_v1/capture_env.py` 실측 결과, 실제로 적용된 context length는 4,096 토큰이었다
(상세: report/environment.md). 재현성을 위해 아래 주석을 해제할 경우 반드시 4096을 유지할 것.
다른 값으로 바꾸면 기존 로그(data/results/local_eval_results.json)와 실행 조건이 달라져 40회 재실험이 필요하다.
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
import ollama

from triage_eval.common.ollama_runtime import get_model_digests, get_vram_mib, sha256_text  # noqa: F401 (v1.3에서 공용 모듈로 이동)
from triage_eval.common.paths import ROOT
from triage_eval.common.preflight import snapshot as preflight_snapshot

# 1. 설정 상수
MODELS = ["qwen2.5:7b", "llama3.1:8b"]
REPEAT_COUNT = 2
OPTIONS = {
    "temperature": 0.2,
    "num_predict": 350,
    # "num_ctx": 4096,   # 실험 당시 실측값. 고정하려면 해제 (단, 위 주의사항 참고)
}

SYSTEM_PROMPT = """당신은 8년 차 게임 QA 엔지니어의 버그 리포트 1차 트리아지 어시스턴트입니다.
제시된 버그 리포트를 엄격하게 분석하여 반드시 아래 5개 필드 규격만 사용하여 작성하세요. 서두나 사족은 절대 출력하지 마세요.

[요약]: 결함 현상 1줄 요약
[모듈]: 전투, 결제, UI, 그래픽, 시스템, 네트워크 등 중 택1 (복합 이슈 시 병기)
[심각도]: Blocker, Critical, Major, Minor, Trivial, 판단보류 중 택1
[재현 여부]: 발생(100%), 간헐적, 불명확, 재현 불가 중 택1
[누락 정보 및 권장 조치]: 추가 확인이 필요한 기기/OS/재현스텝 또는 QA 권장 조치
"""

def options_for_run(seed_base: int | None, run_idx: int) -> dict:
    """회차별 생성 옵션. seed 고정 모드면 OPTIONS 에 회차별 seed 를 더한다 (설계 의도 9)."""
    if seed_base is None:
        return dict(OPTIONS)
    return {**OPTIONS, "seed": seed_base + run_idx - 1}

def execute_single_inference(client: ollama.Client, model: str, report_text: str,
                             options: dict | None = None) -> dict:
    """단일 추론을 수행하고 성능 메타데이터를 반환합니다."""
    prompt = f"{SYSTEM_PROMPT}\n\n[버그 리포트]\n{report_text}"
    start_time = time.perf_counter()
    
    try:
        response = client.generate(
            model=model,
            prompt=prompt,
            options=options if options is not None else OPTIONS,
        )
        elapsed_sec = round(time.perf_counter() - start_time, 3)
        vram_mib = get_vram_mib(client, model)

        load_duration_sec = round(response.get("load_duration", 0) / 1_000_000_000, 3)
        eval_duration_ns = response.get("eval_duration", 0)
        eval_count = response.get("eval_count", 0)

        # eval_duration이 0 초과일 때만 tokens/s 계산 (결측 시 None)
        tokens_per_sec = (
            round(eval_count / (eval_duration_ns / 1_000_000_000), 2)
            if eval_duration_ns > 0
            else None
        )

        return {
            "success": True,
            "response_text": response.get("response", "").strip(),
            "elapsed_sec": elapsed_sec,
            "load_duration_sec": load_duration_sec,
            "eval_count": eval_count,
            "tokens_per_sec": tokens_per_sec,
            "vram_mib": vram_mib,
            "error_message": None,
        }
    except Exception as e:
        elapsed_sec = round(time.perf_counter() - start_time, 3)
        return {
            "success": False,
            "response_text": "",
            "elapsed_sec": elapsed_sec,
            "load_duration_sec": 0.0,
            "eval_count": 0,
            "tokens_per_sec": None,
            "vram_mib": get_vram_mib(client, model),
            "error_message": str(e),
        }

def main():
    parser = argparse.ArgumentParser(description="로컬 40회 벤치마크 실행")
    parser.add_argument("--update-latest", action="store_true",
                        help="이번 결과로 data/results/local_eval_results.json(문서 수치의 출처)도 교체")
    parser.add_argument("--seed", type=int, default=None,
                        help="seed 고정 모드. 1회차 seed=N, 2회차 seed=N+1 (기본: 고정 안 함)")
    parser.add_argument("--strict-env", action="store_true",
                        help="측정 환경 경고(다른 프로그램의 GPU 사용, 배터리 구동 등)가 있으면 실행하지 않음")
    args = parser.parse_args()

    root_dir = ROOT
    data_path = root_dir / "data" / "questions.json"
    results_dir = root_dir / "data" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    with data_path.open("r", encoding="utf-8") as f:
        questions_data = json.load(f)
    questions = questions_data["questions"]

    client = ollama.Client()

    # 측정 환경 점검 (설계 의도 10)
    environment = preflight_snapshot(client)
    print("=== 측정 환경 점검 ===")
    print(f"GPU 사용 중 VRAM: {environment['gpu_used_mib']} MiB "
          f"(Ollama 외 {environment['other_vram_mib']} MiB) · 전원 연결: {environment['on_ac_power']}")
    for w in environment["warnings"]:
        print(f"  ⚠️  {w}")
    for n in environment.get("notes", []):
        print(f"  ℹ️  {n}")
    if environment["warnings"] and args.strict_env:
        print("\n--strict-env: 측정 환경 경고가 있어 실행하지 않습니다. 위 항목을 정리한 뒤 다시 실행하세요.")
        raise SystemExit(2)
    if not environment["warnings"]:
        print("  ✅ 경고 없음")

    seeds = None if args.seed is None else {str(i): args.seed + i - 1 for i in range(1, REPEAT_COUNT + 1)}
    run_config = {
        "options": OPTIONS,
        "repeat_count": REPEAT_COUNT,
        "system_prompt_sha256": sha256_text(SYSTEM_PROMPT),
        # 파일 바이트가 아니라 파싱한 내용으로 지문을 만든다.
        # Windows(CRLF)/Linux(LF) 줄바꿈 차이만으로 "문항이 바뀌었다"고 오판하지 않기 위해서다.
        "questions_sha256": sha256_text(json.dumps(questions_data, ensure_ascii=False, sort_keys=True)),
        "question_ids": [q["id"] for q in questions],
        "model_digests": get_model_digests(client, MODELS),
        "seeds": seeds,
        "environment": environment,
    }
    print(f"seed 고정 모드: {seeds if seeds else '사용 안 함'}\n")
    benchmark_records = []
    warmup_records = []

    print(f"=== 배치 실험 시작: 총 {len(MODELS)}개 모델 × 질문 {len(questions)}개 × {REPEAT_COUNT}회 = {len(MODELS) * len(questions) * REPEAT_COUNT}회 ===")

    for model in MODELS:
        print(f"\n[{model}] 워밍업(Warm-up) 실행 중 (본 통계 집계 제외)...")
        warmup_res = execute_single_inference(client, model, "테스트 워밍업 입력: 게임 접속 불가 현상")
        warmup_record = {
            "model": model,
            "is_warmup": True,
            "timestamp": datetime.now().isoformat(),
            **warmup_res,
        }
        warmup_records.append(warmup_record)
        print(f"[{model}] 워밍업 완료: 소요 {warmup_res['elapsed_sec']}s (로드 {warmup_res['load_duration_sec']}s)")

        # 본 실험 루프 (2회 반복)
        for run_idx in range(1, REPEAT_COUNT + 1):
            print(f"\n--- [{model}] 회차 {run_idx}/{REPEAT_COUNT} 시작 ---")
            for q_idx, q in enumerate(questions, start=1):
                q_id = q["id"]
                print(f"[{model}] [Run {run_idx}] ({q_idx}/{len(questions)}) {q_id}: {q['title'][:20]}... ", end="", flush=True)

                run_options = options_for_run(args.seed, run_idx)
                res = execute_single_inference(client, model, q["report_text"], run_options)

                record = {
                    "eval_id": f"{model.replace(':', '_')}_{q_id}_run{run_idx}",
                    "model": model,
                    "run_index": run_idx,
                    "is_warmup": False,
                    "question_id": q_id,
                    "question_type": q["type"],
                    "cloud_eval": q["cloud_eval"],
                    "seed": run_options.get("seed"),
                    "timestamp": datetime.now().isoformat(),
                    **res,
                }
                benchmark_records.append(record)

                if res["success"]:
                    print(f"성공 ({res['elapsed_sec']}s, {res['tokens_per_sec']} t/s, VRAM {res['vram_mib']} MiB)")
                else:
                    print(f"실패 - 사유: {res['error_message']}")

    # 최종 결과 파일 저장
    output_payload = {
        "metadata": {
            "project": questions_data.get("project", "Aether Raid Bug Triage"),
            "executed_at": datetime.now().isoformat(),
            "models": MODELS,
            "total_formal_runs": len(benchmark_records),
            "warmup_runs": len(warmup_records),
            "run_config": run_config,
        },
        "warmup_runs": warmup_records,
        "results": benchmark_records,
    }

    # 실행 기록 — 항상 저장. compare_runs.py 의 기본 후보가 된다.
    history_dir = results_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    history_file = history_dir / f"local_eval_results_{run_stamp}.json"
    with history_file.open("w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    print(f"\n=== 전체 {len(benchmark_records)}회 실험 완료 ===")
    print(f"실행 기록: {history_file.resolve()}")

    # 문서 기준 파일 — 명시적으로 요청했을 때만 교체 (설계 의도 8)
    if args.update_latest:
        output_file = results_dir / "local_eval_results.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False, indent=2)
        print(f"문서 기준 파일 교체: {output_file.resolve()}")
        print("  → README·보고서 수치를 summarize_eval.py / score_format.py 로 다시 맞춰야 합니다.")
    else:
        print("문서 기준 파일(local_eval_results.json)은 그대로 두었습니다. 교체하려면 --update-latest")
    print("회귀 판정: uv run bench-gate")

if __name__ == "__main__":
    main()