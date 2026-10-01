"""v1.3 평가셋(data/eval_v13/aether_raid_v13.json) 검증.

모델을 호출하지 않으므로 CI에서 자동 실행된다.
- 저장소에 올라간 JSON이 생성 스크립트(tools/dataset_v13/)의 결과와 같은가
  → 누군가 JSON만 손으로 고치면 라벨의 근거(스크립트·검토 기록)와 어긋나므로 잡아낸다.
- 라벨 값과 규칙 간 일관성 검사(merge_dataset.validate)가 실제로 오류를 잡는가
- 개발용/평가용 분할이 위험 건 측정 문항을 반씩 나눴는가
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "dataset_v13"))

import merge_dataset as m  # noqa: E402

DATA_PATH = ROOT / "data" / "eval_v13" / "aether_raid_v13.json"


def load():
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def test_committed_file_matches_generators():
    built, errors = m.build()
    assert errors == []
    # 텍스트가 아니라 파싱한 내용으로 비교한다 (Windows 체크아웃의 CRLF 차이 무시)
    assert load() == json.loads(m.dump(built))


def test_counts_and_unique_ids():
    d = load()
    ids = [i["id"] for i in d["items"]]
    assert len(ids) == 63 == len(set(ids))
    assert d["counts"] == {"total": 63, "representative": 40, "focused": 23}


def test_split_is_balanced():
    d = load()
    for s in ("representative", "focused"):
        sub = [i for i in d["items"] if i["set"] == s]
        dev = [i for i in sub if i["split"] == "dev"]
        test = [i for i in sub if i["split"] == "test"]
        assert abs(len(dev) - len(test)) <= 1
        for key in ("X-1", "X-3"):
            nd = sum(key in i["labels"]["risk"] for i in dev)
            nt = sum(key in i["labels"]["risk"] for i in test)
            assert abs(nd - nt) <= 1, (s, key, nd, nt)


def _item(**label_overrides):
    it = copy.deepcopy(next(i for i in load()["items"] if i["id"] == "B04"))
    it["labels"].update(label_overrides)
    return it


def test_validate_rejects_unknown_enum():
    errs = m.validate([_item(처리=["즉시 전달"])])  # v1.3에서 '긴급 사인 요청'으로 바뀐 옛 값
    assert any("허용 밖 값" in e for e in errs)


def test_validate_rejects_x1_without_sign_request():
    errs = m.validate([_item(우선순위=["Critical"], risk=["X-1"], 처리=["개발 배정"])])
    assert any("X-1" in e for e in errs)


def test_validate_rejects_track_a_dev_assign_for_defect():
    it = copy.deepcopy(next(i for i in load()["items"] if i["id"] == "A01"))
    it["labels"]["처리"] = ["개발 배정"]
    assert any("트랙 A에 개발 배정" in e for e in m.validate([it]))


def test_validate_rejects_once_critical_outside_exceptions():
    # 1회 + Critical 은 결제·데이터 소실·서버 장애일 때만 허용 (기준서 F-2)
    it = _item(우선순위=["Critical"], 처리=["긴급 사인 요청"], 모듈=["그래픽·사운드"])
    it["labels"]["발생 빈도"] = ["1회"]
    assert any("F-2" in e for e in m.validate([it]))
