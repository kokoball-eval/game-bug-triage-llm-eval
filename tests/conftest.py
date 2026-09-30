"""pytest 공통 준비물.

- src/ 는 pyproject.toml 의 [tool.pytest.ini_options] pythonpath 설정으로 import 경로에 들어간다.
- 테스트는 저장소의 실제 로그를 "읽기만" 한다. 변형이 필요한 로그는 메모리에서 복사해 고치고,
  파일이 필요하면 pytest 가 주는 임시 폴더(tmp_path)에 쓴다. 저장소 파일은 절대 바꾸지 않는다.
"""

import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = ROOT / "data" / "results" / "baseline" / "v1.0_local_eval_results.json"

QWEN = "qwen2.5:7b"
LLAMA = "llama3.1:8b"


@pytest.fixture(scope="session")
def _baseline_raw() -> dict:
    return json.loads(BASELINE_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def baseline(_baseline_raw) -> dict:
    """v1.0 기준선 로그. 테스트마다 새 복사본을 주므로 마음껏 고쳐도 다른 테스트에 영향이 없다."""
    return copy.deepcopy(_baseline_raw)


@pytest.fixture
def write_json(tmp_path):
    """dict 를 임시 폴더의 JSON 파일로 저장하고 경로를 돌려주는 도우미."""
    def _write(name: str, payload: dict) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path
    return _write
