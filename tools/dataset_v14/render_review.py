"""v1.4 최종 평가용 세트 25건의 검토 문서를 생성한다.

사용: uv run python tools/dataset_v14/render_review.py
출력: docs/dataset/final_v14_review.md

문서는 final_v14_items.py에서 만들어지므로 라벨과 문서가 어긋나지 않는다.
"""

import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from final_v14_items import ITEMS, KNOWN_BASE, UPDATE_NOTE  # noqa: E402

OUT = ROOT / "docs" / "dataset" / "final_v14_review.md"


def j(v):
    return " / ".join(v) if v else "—"


def render() -> str:
    c = Counter(i["track"] for i in ITEMS)
    r = Counter(x for i in ITEMS for x in i["labels"]["risk"])
    out = [
        "# v1.4 최종 평가용 세트 (25건)", "",
        "> 이 문서는 `tools/dataset_v14/render_review.py`가 `final_v14_items.py`에서 생성합니다. 라벨을 고칠 때는 스크립트를 고치고 다시 생성합니다.",
        "> 이 25건은 방법 선택(실험 A·B)이 끝날 때까지 어떤 모델에도 실행하지 않고, 최종 측정에서 1회만 사용합니다. 검토 과정은 [검토 기록](review_log.md)에 있습니다.",
        "", "## 1. 구성", "",
        f"- 트랙 A {c['A']}건 / 트랙 B {c['B']}건",
        f"- 위험 건 측정: X-1 {r['X-1']}건, X-2 {r['X-2']}건, X-3 {r['X-3']}건",
        "- 첫 정답 분류: " + ", ".join(f"{k} {v}" for k, v in Counter(i["labels"]["분류"][0] for i in ITEMS).items()),
        "- 첫 정답 우선순위: " + ", ".join(f"{k} {v}" for k, v in Counter(i["labels"]["우선순위"][0] for i in ITEMS).items()),
        f"- 공통 맥락: {UPDATE_NOTE}",
        "- 등록된 이슈(중복 판정용): " + " · ".join(KNOWN_BASE),
        "- 기존 63건과 겹치지 않도록 업데이트 버전, 지역, 아이템 이름을 새로 정했고, 문항마다 기존 문항과의 겹침 정도를 표시했습니다(`new` 새 상황, `type` 유형만 같음, `overlap` 상황이 가까움).",
        "", "## 2. 라벨 요약 (각 칸은 허용 답, 첫 번째가 가장 바람직한 답)", "",
        "| 문항 | 트랙 | 제목 | 분류 | 우선순위 | 처리 | 빈도 | 위험 | 사람 검토 |",
        "| :---: | :---: | :--- | :--- | :--- | :--- | :--- | :--- | :---: |",
    ]
    for i in ITEMS:
        lb = i["labels"]
        out.append(f"| {i['id']} | {i['track']} | {i['input']['title']} | {j(lb['분류'])} | {j(lb['우선순위'])} | "
                   f"{j(lb['처리'])} | {j(lb['발생 빈도'])} | {j(lb['risk'])} | {'O' if lb['human_review'] else ''} |")
    out += ["", "## 3. 문항 전문", ""]
    for i in ITEMS:
        inp, lb = i["input"], i["labels"]
        head = f"{inp['board']} · {inp['posted_at']}" if i["track"] == "A" else f"작성: {inp['reporter']}"
        out += [f"### {i['id']} · {inp['title']}", "", f"트랙 {i['track']} · {i['quality']} · {head}", "",
                "```text", inp["body"], "```", "",
                f"- 분류: {j(lb['분류'])} / 우선순위: {j(lb['우선순위'])} / 모듈: {j(lb['모듈'])} / 재현 정보: {j(lb['재현 정보'])}",
                f"- 처리: {j(lb['처리'])} / 발생 빈도: {j(lb['발생 빈도'])} / 위험: {j(lb['risk'])} / 사람 검토: {'예' if lb['human_review'] else '아니오'}"]
        if lb["must_request"]:
            out.append(f"- 반드시 요청: {j(lb['must_request'])}")
        if lb["must_recommend"]:
            out.append(f"- 반드시 권장: {j(lb['must_recommend'])}")
        out += [f"- 근거: {i['rationale']}", f"- 기존 문항과 겹침: {i['overlap']}", ""]
    return "\n".join(out)


def main():
    OUT.write_text(render(), encoding="utf-8")
    print(f"생성 완료: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
