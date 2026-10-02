"""Ollama 실행 정보 수집 — v1.0 벤치마크(bench_v1.run_eval)와 현역 파이프라인(pipeline.run)이 함께 쓴다.

v1.3 구조 정리 때 bench_v1/run_eval.py 에서 그대로 옮겼다. 함수 본문은 바꾸지 않았다
(v1.0 실행 기록의 vram_mib·model_digests·system_prompt_sha256 값이 같은 방식으로 계산되어야 한다).
"""

import hashlib

import ollama


def get_vram_mib(client: ollama.Client, model_name: str) -> float:
    """추론 직후 ollama ps에서 해당 모델의 VRAM 점유량(MiB)을 추출합니다."""
    try:
        ps = client.ps()
        for m in ps.get("models", []):
            name = m.get("name", "")
            if name == model_name or name.startswith(model_name.split(":")[0]):
                return round(m.get("size_vram", 0) / (1024 * 1024), 2)
    except Exception:
        pass
    return 0.0

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def get_model_digests(client: ollama.Client, models: list[str]) -> dict:
    """ollama list 에서 모델별 digest 앞 12자리를 읽는다. 같은 태그라도 재pull 하면 바뀔 수 있다."""
    digests = {}
    try:
        for m in client.list().get("models", []):
            name = m.get("model") or m.get("name", "")
            if name in models:
                digests[name] = (m.get("digest") or "")[:12] or None
    except Exception:
        pass
    return {model: digests.get(model) for model in models}
