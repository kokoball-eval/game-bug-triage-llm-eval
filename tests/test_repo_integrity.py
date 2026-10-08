"""저장소 정합성 테스트 — 커밋한 설정·데이터 파일이 실제로 읽히는지 확인한다.

v1.5 라벨 일치율 기준 파일(label_agreement_v15.toml)은 그 파일을 읽는 코드보다 먼저 커밋되어, TOML 문법 오류
(따옴표 없는 한글 키)가 계산 도구를 만들 때까지 드러나지 않았다. 측정 전에 커밋하는 기준 파일은 읽는 코드가 늦게
생기는 경우가 많으므로, 파일이 커밋되는 시점에 바로 읽어 보는 테스트를 둔다.
"""

import importlib
import json
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKIP = {".git", ".venv", "dist", "__pycache__", ".pytest_cache", "Claude outputs"}


def repo_files(suffix: str) -> list[Path]:
    """저장소에 커밋된 파일만 본다. 로컬 작업 폴더(.gitignore 대상)에 둔 사본·생성물은 저장소 결과물이 아니다.
    git을 쓸 수 없는 환경이면 폴더를 훑되 알려진 작업 폴더는 뺀다."""
    try:
        out = subprocess.run(["git", "ls-files", "-z", f"*{suffix}"], cwd=ROOT, capture_output=True, check=True)
        return sorted(ROOT / f for f in out.stdout.decode("utf-8").split("\0") if f)
    except (OSError, subprocess.CalledProcessError):
        return sorted(p for p in ROOT.rglob(f"*{suffix}") if not SKIP & set(p.relative_to(ROOT).parts))


@pytest.mark.parametrize("path", repo_files(".toml"), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_toml_parses(path):
    tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", repo_files(".json"), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_json_parses(path):
    json.loads(path.read_text(encoding="utf-8"))


def loaders():
    """저장소 루트의 기준 파일 → 그 파일을 읽는 함수. 새 기준 파일을 추가하면 여기에 등록해야 테스트가 통과한다."""
    from triage_eval.bench_v1 import compare_runs
    from triage_eval.pipeline import agreement, compare, gate, gate_v14, selection

    return {
        "gate_criteria.toml": lambda p: compare_runs.validate_criteria(tomllib.loads(p.read_text(encoding="utf-8"))),
        "gate_criteria_v13.toml": gate.load_criteria,
        "gate_criteria_v14.toml": gate_v14.load_criteria,
        "model_selection_v14.toml": selection.load_select_criteria,
        "method_selection_v14.toml": compare.load_criteria,
        "label_agreement_v15.toml": agreement.load_criteria,
    }


def test_every_root_criteria_file_has_a_loader():
    """루트의 기준 파일은 모두 읽는 함수가 등록되어 있다 — 읽는 코드 없이 커밋된 기준 파일을 막는다."""
    root_tomls = {p.name for p in ROOT.glob("*.toml")} - {"pyproject.toml"}
    assert root_tomls == set(loaders())


@pytest.mark.parametrize("name", ["gate_criteria.toml", "gate_criteria_v13.toml", "gate_criteria_v14.toml",
                                  "model_selection_v14.toml", "method_selection_v14.toml", "label_agreement_v15.toml"])
def test_every_criteria_file_passes_its_loader(name):
    """문법뿐 아니라 각 도구의 키 검사(모르는 섹션·키, 빠진 키)까지 통과한다."""
    loaders()[name](ROOT / name)


def test_every_console_script_resolves():
    """pyproject.toml 의 실행 명령이 모두 실제 함수를 가리킨다."""
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    for name, target in scripts.items():
        module, func = target.split(":")
        assert callable(getattr(importlib.import_module(module), func)), name
