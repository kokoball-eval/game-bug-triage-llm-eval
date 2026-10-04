"""v1.4 평가셋(data/eval_v14/aether_raid_v14.json) 검증.

모델을 호출하지 않으므로 CI에서 자동 실행된다.
- 저장소에 올라간 JSON이 생성 스크립트(tools/dataset_v14/)의 결과와 같은가
- v1.3의 63건이 라벨 변경 없이 모두 개발용으로 넘어왔는가 (Minor↔Trivial 상호 허용 추가만 예외)
- 최종 평가용 25건이 기존 문항과 ID·원문이 겹치지 않는가
- 트랙 A 개발 배정 규칙의 완화가 의도한 범위에서만 동작하는가
"""

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools" / "dataset_v14"))

import build_v14 as m  # noqa: E402

DATA_PATH = ROOT / "data" / "eval_v14" / "aether_raid_v14.json"
V13_PATH = ROOT / "data" / "eval_v13" / "aether_raid_v13.json"


def load(path=DATA_PATH):
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_file_matches_generators():
    built, errors = m.build()
    assert errors == []
    assert load() == json.loads(m.dump(built))


def test_counts_and_splits():
    d = load()
    ids = [i["id"] for i in d["items"]]
    assert len(ids) == 88 == len(set(ids))
    assert d["counts"] == {"total": 88, "dev": 63, "final": 25}
    assert {i["split"] for i in d["items"]} == {"dev", "final"}
    assert all(i["id"].startswith("F") for i in d["items"] if i["split"] == "final")


def test_v13_items_carried_over_unchanged():
    # v1.3의 63건은 분할만 dev로 바뀌고, 원래 분할은 split_v13에 남는다. 나머지는 한 글자도 바뀌지 않아야 한다.
    v13 = {i["id"]: i for i in load(V13_PATH)["items"]}
    dev = [i for i in load()["items"] if i["split"] == "dev"]
    assert {i["id"] for i in dev} == set(v13)
    for it in dev:
        it = copy.deepcopy(it)
        assert it.pop("split_v13") == v13[it["id"]]["split"]
        it["split"] = v13[it["id"]]["split"]
        if it.pop("label_relaxed", None):
            pri = it["labels"]["우선순위"]
            assert pri[:-1] == v13[it["id"]]["labels"]["우선순위"]   # 끝에 하나만 더해졌다
            it["labels"]["우선순위"] = pri[:-1]
        assert it == v13[it["id"]], it["id"]


def test_final_items_do_not_reuse_existing_text():
    items = load()["items"]
    old = [i for i in items if i["split"] == "dev"]
    new = [i for i in items if i["split"] == "final"]
    old_titles = {i["input"]["title"] for i in old}
    old_bodies = {i["input"]["body"] for i in old}
    for it in new:
        assert it["input"]["title"] not in old_titles, it["id"]
        assert it["input"]["body"] not in old_bodies, it["id"]
        assert it["review"] == "approved"


def _final(id_):
    return copy.deepcopy(next(i for i in m.FINAL_ITEMS if i["id"] == id_))


def test_relaxed_rule_allows_dev_assign_when_improvement_is_allowed():
    # F22: 첫 정답은 문의·건의, 개선 제안도 허용 → 개발 배정 허용
    assert m.validate([_final("F22")]) == []


def test_relaxed_rule_still_rejects_defect_dev_assign_on_track_a():
    it = _final("F08")
    it["labels"]["처리"] = ["등록(재현 대기)", "개발 배정"]
    assert any(m.TRACK_A_RULE in e for e in m.validate([it]))


def test_v13_rules_still_apply():
    it = _final("F02")
    it["labels"]["처리"] = ["개발 배정"]   # X-1 측정 문항인데 긴급 사인 요청이 없음
    assert any("X-1" in e for e in m.validate([it]))


def test_minor_trivial_relaxation_scope():
    """첫 정답이 Minor/Trivial인 문항만 다른 쪽을 허용하고, 첫 정답은 그대로 둔다."""
    for it in load()["items"]:
        pri = it["labels"]["우선순위"]
        if pri[0] in ("Minor", "Trivial"):
            assert {"Minor", "Trivial"} <= set(pri), it["id"]
        else:
            assert "label_relaxed" not in it, it["id"]
    final = next(i for i in load()["items"] if i["id"] == "F15")
    assert final["labels"]["우선순위"] == ["Minor", "Trivial"]
    a08 = next(i for i in load()["items"] if i["id"] == "A08")   # 첫 정답 Major — 바꾸지 않음
    assert a08["labels"]["우선순위"] == ["Major", "Minor"]
