"""저장소 루트 경로 — 한 곳에서만 정의한다.

이 파일의 위치: <저장소>/src/triage_eval/common/paths.py → parents[3] 이 저장소 루트다.
각 모듈이 Path(__file__).parent.parent 처럼 자기 위치에서 루트를 계산하면, 폴더 구조를 바꿀 때
모든 모듈이 한꺼번에 틀린다(v1.3 구조 정리 전에는 9곳에서 따로 계산했다).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
