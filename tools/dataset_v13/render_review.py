"""평가셋 배치 JSON → 검토용 마크다운."""
import json, sys
from pathlib import Path

def render(path: Path) -> str:
    d = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for it in d["items"]:
        inp, lb = it["input"], it["labels"]
        head = f"### {it['id']} · {it['quality']}" + (f" · `{it['split']}`" if it.get("split") else "")
        out.append(head)
        if it["track"] == "A":
            out.append(f"`{inp['board']}` · {inp['posted_at']}\n")
            out.append(f"**{inp['title']}**\n")
            out.append("\n".join("> " + line for line in inp["body"].split("\n")) + "\n")
        else:
            out.append(f"`{inp['reporter']}`\n")
            out.append(f"**{inp['title']}**\n")
            out.append("\n".join("> " + line if line else ">" for line in inp["body"].split("\n")) + "\n")
        def j(v): return " / ".join(v) if v else "—"
        freq = lb.get("발생 빈도")
        out.append("| 분류 | 우선순위 | 모듈 | 재현 정보 |" + (" 발생 빈도 |" if freq else "") + " 처리 | 사람 검토 | 위험 건 |")
        out.append("| :--- | :--- | :--- | :--- |" + (" :--- |" if freq else "") + " :--- | :---: | :---: |")
        out.append(f"| {j(lb['분류'])} | {j(lb['우선순위'])} | {j(lb['모듈'])} | {j(lb['재현 정보'])} | " + (f"{j(freq)} | " if freq else "") + f"{j(lb['처리'])} | "
                   f"{'필요' if lb['human_review'] else '—'} | {j(lb['risk'])} |\n")
        if lb["must_request"]:
            out.append(f"- **반드시 요청할 정보:** {', '.join(lb['must_request'])}")
        if lb.get("must_recommend"):
            out.append(f"- **반드시 권장할 조치:** {', '.join(lb['must_recommend'])}")
        out.append(f"- **근거:** {it['rationale']}")
        known = inp.get("context", {}).get("known_issues", [])
        note = inp.get("context", {}).get("update_note", "")
        if "\n" in note:
            out.append(f"- **이 문항에만 있는 공지:** {' / '.join(note.split(chr(10))[1:])}")
        if len(known) > 3:
            out.append(f"- **이 문항에만 있는 기존 등록 이슈:** {known[-1]}")
        out.append("- **검토:** ☐ OK ☐ 수정\n")
    return "\n".join(out)

if __name__ == "__main__":
    print(render(Path(sys.argv[1])))
