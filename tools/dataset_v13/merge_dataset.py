"""v1.3 평가셋 병합 — 승인된 배치 5개를 하나로 합치고, 개발용/평가용으로 나누고, 형식을 검증한다.

사용: uv run python tools/dataset_v13/merge_dataset.py
출력: data/eval_v13/aether_raid_v13.json

정답 라벨의 원본은 배치 스크립트(batch*.py)와 frequency_labels.py 이고, JSON은 그 결과물이다.
라벨을 고칠 때는 스크립트를 고치고 이 파일을 다시 실행한다 (tests/test_dataset_v13.py 가 둘의 일치를 확인).

설계 메모
- 분할은 무작위가 아니라 "위험 건 측정 문항 → 층(stratum)" 순으로 정렬해 번갈아 배정한다. 같은 성격의 문항(예: 트랙 B 명확형, 집중 세트 경계형)이
  dev와 test에 반씩 들어가야, test 점수가 dev 점수와 같은 문제를 재고 있다고 말할 수 있다.
  무작위 분할은 63건처럼 작은 셋에서 한쪽에 Critical이 몰리는 일이 쉽게 생긴다.
- 같은 입력이면 항상 같은 분할이 나오도록 정렬 순서만으로 결정한다(난수 없음) → 재실행해도 결과가 바뀌지 않는다.
- 검증에 실패하면 파일을 쓰지 않고 종료 코드 1로 끝낸다(평가 게이트의 "판단 불가" 원칙과 같은 생각).
"""

import copy
import importlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from frequency_labels import FREQUENCY, FREQ_REVIEW  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "eval_v13" / "aether_raid_v13.json"
BATCH_MODULES = ["batch1_track_a", "batch2", "batch3", "batch4_focused", "batch5_focused"]

ENUMS = {
    "분류": ["결함", "개선 제안", "버그 아님", "문의·건의", "중복 의심", "무관"],
    "우선순위": ["Critical", "Major", "Minor", "Trivial", "판단보류", "해당 없음"],
    "모듈": ["클라이언트 안정성", "네트워크", "계정·로그인", "결제·재화", "콘텐츠 진행",
             "게임플레이·밸런스", "그래픽·사운드", "UI·텍스트", "플랫폼 호환성", "보안·어뷰징"],
    "재현 정보": ["충분", "부족"],
    "처리": ["긴급 사인 요청", "등록(재현 대기)", "개발 배정", "정보 요청 후 보류", "CS 응대", "폐기"],
    "발생 빈도": ["항상", "간헐적", "1회", "미기재", "해당 없음"],
}
RISKS = {"X-1", "X-2", "X-3"}


def stratum(it):
    """분할 층: 세트 + 트랙 + 품질의 큰 갈래."""
    q = it["quality"]
    for key in ["명확", "단문", "감정", "복합", "중복", "문의", "무관", "운영 불만형", "경계", "확인 필요", "거짓 경보"]:
        if key in q:
            coarse = key
            break
    else:
        coarse = q
    if "경계" in q and it["set"] == "representative":
        coarse += "(경계)"
    return (it["set"], it["track"], coarse)


def validate(items):
    errors = []
    ids = [it["id"] for it in items]
    for i, n in Counter(ids).items():
        if n > 1:
            errors.append(f"{i}: ID 중복")
    for it in items:
        lb, i = it["labels"], it["id"]
        if it["review"] != "approved":
            errors.append(f"{i}: 승인 안 됨 ({it['review']})")
        for field, allowed in ENUMS.items():
            vals = lb[field]
            if field != "모듈" and not vals:
                errors.append(f"{i}: {field} 비어 있음")
            for v in vals:
                if v not in allowed:
                    errors.append(f"{i}: {field} 허용 밖 값 '{v}'")
        for r in lb["risk"]:
            if r not in RISKS:
                errors.append(f"{i}: 위험 건 값 '{r}'")
        # 규칙 간 일관성
        if it["track"] == "A" and "개발 배정" in lb["처리"] and lb["분류"][0] != "개선 제안":
            errors.append(f"{i}: 트랙 A에 개발 배정 (H-2b는 트랙 B, H-2d는 개선 제안 전용)")
        if (lb["발생 빈도"] == ["1회"] and lb["우선순위"][0] == "Critical"
                and not set(lb["모듈"]) & {"결제·재화", "계정·로그인"} and "H-1b" not in it["rationale"]):
            errors.append(f"{i}: 1회인데 Critical — F-2 예외(결제·데이터 소실·서버 장애)에 해당하지 않음")
        if lb["분류"][0] in ("결함", "중복 의심") and lb["발생 빈도"][0] == "해당 없음":
            errors.append(f"{i}: 결함·중복인데 발생 빈도가 해당 없음")
        if lb["분류"] == ["무관"] and lb["우선순위"] != ["해당 없음"]:
            errors.append(f"{i}: 무관인데 우선순위가 해당 없음이 아님")
        if "X-1" in lb["risk"] and "긴급 사인 요청" not in lb["처리"]:
            errors.append(f"{i}: X-1 측정 문항인데 긴급 사인 요청이 정답에 없음")
        if "X-3" in lb["risk"] and not lb["human_review"]:
            errors.append(f"{i}: X-3 측정 문항인데 사람 검토 표시 없음")
        if lb["처리"][0] == "긴급 사인 요청" and lb["우선순위"][0] not in ("Critical",) and not lb["human_review"]:
            errors.append(f"{i}: 긴급 사인 요청이 첫 정답인데 Critical도 경계 건도 아님")
        if it["track"] == "B" and "reporter" not in it["input"]:
            errors.append(f"{i}: 트랙 B인데 reporter 없음")
    return errors


def split(items):
    """층별로 정렬해 dev/test를 번갈아 배정. 층이 바뀌어도 토글을 이어가 전체 수도 반반이 되게 한다."""
    by_set = {}
    for it in items:
        by_set.setdefault(it["set"], []).append(it)
    for set_items in by_set.values():
        toggle = 0
        # 위험 건 측정 문항(사람 검토·X-1)을 먼저 번갈아 나눈 뒤, 나머지를 층별로 번갈아 나눈다
        key = lambda x: (not x["labels"]["human_review"], "X-1" not in x["labels"]["risk"], stratum(x), x["id"])
        for it in sorted(set_items, key=key):
            it["split"] = "dev" if toggle % 2 == 0 else "test"
            toggle += 1


def summary(items):
    rows = []
    for s in ["representative", "focused"]:
        sub = [i for i in items if i["set"] == s]
        for sp in ["dev", "test"]:
            g = [i for i in sub if i["split"] == sp]
            rows.append({
                "set": s, "split": sp, "n": len(g),
                "Critical(X-1)": sum("X-1" in i["labels"]["risk"] for i in g),
                "결함 폐기 금지(X-2)": sum("X-2" in i["labels"]["risk"] for i in g),
                "사람 검토(X-3)": sum(i["labels"]["human_review"] for i in g),
                "트랙 B": sum(i["track"] == "B" for i in g),
            })
    return rows


def build():
    """배치 스크립트에서 63건을 모아 검증·분할한다. (데이터, 오류 목록)을 돌려주고 파일은 쓰지 않는다."""
    items = []
    for name in BATCH_MODULES:
        items += copy.deepcopy(importlib.import_module(name).ITEMS)
    if set(FREQUENCY) != {it["id"] for it in items}:
        return None, ["발생 빈도 라벨과 문항 ID가 맞지 않음"]
    for it in items:  # [발생 빈도] 라벨은 frequency_labels.py에서 가져온다
        it["labels"]["발생 빈도"] = FREQUENCY[it["id"]]
    errors = validate(items)
    if errors:
        return None, errors
    split(items)
    order = {"representative": 0, "focused": 1}
    items.sort(key=lambda x: (order[x["set"]], x["track"], x["id"]))
    data = {
        "name": "Aether Raid 버그 트리아지 평가셋",
        "version": "v1.3",
        "created": "2026-10-01",
        "guideline": "docs/dataset/triage_guideline.md (v1.3)",
        "review_log": "docs/dataset/review_log.md",
        "label_semantics": "labels의 각 필드는 허용 답 목록이며 첫 번째 값이 가장 바람직한 답",
        "frequency_label_review": FREQ_REVIEW,
        "counts": {"total": len(items), **Counter(i["set"] for i in items)},
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
    print(f"{data['counts']['total']}건 병합·분할·검증 완료: {OUT.relative_to(ROOT)}")
    for r in data["split_summary"]:
        print("  ", r)


if __name__ == "__main__":
    main()
