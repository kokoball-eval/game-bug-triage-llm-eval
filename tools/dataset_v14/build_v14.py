"""v1.4 평가셋 생성 — v1.3의 63건을 모두 개발용으로 돌리고, 새 최종 평가용 세트 25건을 더한다.

사용: uv run python tools/dataset_v14/build_v14.py
출력: data/eval_v14/aether_raid_v14.json

정답 라벨의 원본은 v1.3 배치 스크립트(tools/dataset_v13/)와 final_v14_items.py 이고, JSON은 그 결과물이다.
라벨을 고칠 때는 스크립트를 고치고 이 파일을 다시 실행한다 (tests/test_dataset_v14.py 가 둘의 일치를 확인).

설계 메모
- v1.3 평가셋 파일(data/eval_v13/aether_raid_v13.json)과 생성 스크립트는 건드리지 않는다.
  v1.3 실행 기록·보고서·게이트가 그 파일을 기준으로 재현되어야 하기 때문이다. v1.4는 새 파일을 만든다.
- v1.3 평가용(test) 31건은 v1.3 최종 측정에서 결과를 이미 보았으므로 더 이상 평가용이 될 수 없다.
  그래서 63건 전부를 개발용(dev)으로 두고, 원래 분할은 `split_v13`에 남긴다.
- 새 25건의 분할 이름은 `final`이다. 기존 실행 스크립트의 --split 선택지(dev/test/all)에 없는 이름이라,
  실행 스크립트를 v1.4용으로 고치기 전까지는 실수로라도 실행될 수 없다.
- 검증은 v1.3의 merge_dataset.validate를 그대로 쓰되, 트랙 A 개발 배정 규칙 하나만 완화한다(아래 validate 참고).
  v1.3 도구의 규칙은 바꾸지 않는다.
- 검증에 실패하면 파일을 쓰지 않고 종료 코드 1로 끝낸다.
- (2026-10-04) Minor와 Trivial의 경계는 서로 허용한다(relax_minor_trivial). 우선순위의 첫 정답이 Minor면 Trivial을,
  Trivial이면 Minor를 허용 답 끝에 더한다. 첫 정답(가장 바람직한 답)은 그대로이고, Major 이상·판단보류·해당 없음이
  첫 정답인 문항은 바꾸지 않는다. 라벨 원본(v1.3 배치 스크립트, final_v14_items.py)은 고치지 않고 생성 단계에서 적용해,
  어느 문항이 이 규칙으로 바뀌었는지 `label_relaxed`로 남긴다. 방법 비교 측정 전에 정했다(기준서 v1.4 §4.1).
"""

import copy
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "dataset_v13"))

import merge_dataset as v13  # noqa: E402
from final_v14_items import ITEMS as FINAL_ITEMS  # noqa: E402

OUT = ROOT / "data" / "eval_v14" / "aether_raid_v14.json"
TRACK_A_RULE = "트랙 A에 개발 배정"
NEIGHBOR = {"Minor": "Trivial", "Trivial": "Minor"}


def relax_minor_trivial(item):
    """첫 정답이 Minor/Trivial이면 다른 쪽을 허용 답에 더한다. 바꿨으면 True."""
    pri = item["labels"]["우선순위"]
    other = NEIGHBOR.get(pri[0]) if pri else None
    if other is None or other in pri:
        return False
    pri.append(other)
    item["label_relaxed"] = ["우선순위: Minor↔Trivial 상호 허용"]
    return True


def validate(items):
    """v1.3 검증 + 트랙 A 개발 배정 규칙 완화.

    v1.3 규칙: 트랙 A에서 개발 배정은 첫 정답 분류가 개선 제안일 때만 허용.
    v1.4 규칙: 허용 분류에 개선 제안이 있으면 허용 (F22처럼 문의·건의가 첫 정답이고 개선 제안도 허용하는 경우).
    개선 제안이 아예 없는 트랙 A 문항의 개발 배정은 그대로 오류다.
    """
    errors = [e for e in v13.validate(items) if TRACK_A_RULE not in e]
    for it in items:
        lb = it["labels"]
        if it["track"] == "A" and "개발 배정" in lb["처리"] and "개선 제안" not in lb["분류"]:
            errors.append(f"{it['id']}: {TRACK_A_RULE} (H-2b는 트랙 B, H-2d는 개선 제안 전용)")
    return errors


def summary(items):
    rows = []
    for sp in ["dev", "final"]:
        g = [i for i in items if i["split"] == sp]
        rows.append({
            "split": sp, "n": len(g),
            "트랙 B": sum(i["track"] == "B" for i in g),
            "Critical(X-1)": sum("X-1" in i["labels"]["risk"] for i in g),
            "결함 폐기 금지(X-2)": sum("X-2" in i["labels"]["risk"] for i in g),
            "사람 검토(X-3)": sum(i["labels"]["human_review"] for i in g),
        })
    return rows


def build():
    """(데이터, 오류 목록)을 돌려주고 파일은 쓰지 않는다."""
    v13_data, errors = v13.build()
    if errors:
        return None, ["v1.3 평가셋 생성 실패: " + e for e in errors]
    dev = copy.deepcopy(v13_data["items"])
    for it in dev:
        it["split_v13"] = it["split"]
        it["split"] = "dev"
    final = copy.deepcopy(FINAL_ITEMS)
    ids = {i["id"] for i in dev}
    errors = [f"{i['id']}: v1.3 문항과 ID 중복" for i in final if i["id"] in ids]
    errors += validate(final)
    if errors:
        return None, errors
    items = dev + final
    relaxed = [it["id"] for it in items if relax_minor_trivial(it)]
    errors = validate(items)
    if errors:
        return None, errors
    data = {
        "name": "Aether Raid 버그 트리아지 평가셋",
        "version": "v1.4",
        "created": "2026-10-03",
        "guideline": "docs/dataset/triage_guideline.md (v1.4)",
        "review_log": "docs/dataset/review_log.md",
        "label_semantics": "labels의 각 필드는 허용 답 목록이며 첫 번째 값이 가장 바람직한 답",
        "split_policy": "dev = v1.3의 63건 전부(원래 분할은 split_v13), final = v1.4 신규 25건(방법 선택이 끝난 뒤 1회만 실행)",
        "label_policy": "우선순위 첫 정답이 Minor 또는 Trivial인 문항은 다른 쪽도 허용 (label_relaxed 표시, 기준서 v1.4 §4.1)",
        "label_relaxed_ids": relaxed,
        "counts": {"total": len(items), **Counter(i["split"] for i in items)},
        "split_summary": summary(items),
        "items": items,
    }
    return data, []


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main():
    data, errors = build()
    if errors:
        print("검증 실패 — 파일을 쓰지 않습니다")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(dump(data), encoding="utf-8")
    print(f"{data['counts']['total']}건 생성·검증 완료: {OUT.relative_to(ROOT)}")
    for r in data["split_summary"]:
        print("  ", r)


if __name__ == "__main__":
    main()
