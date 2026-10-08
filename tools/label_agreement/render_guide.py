"""v1.5 라벨 일치율 — 채점자 안내서(docs/label_agreement/rater_guide.md)를 PDF로 만든다.

사용법
------
    uv run --with markdown --with playwright python tools/label_agreement/render_guide.py --out <폴더>

[설계 의도]
1. 안내서의 원본은 저장소의 마크다운 하나다. 채점자에게 보내는 PDF는 이 원본에서만 만들어, 저장소 문서와 받은 문서가 어긋나지 않게 한다.
2. 마크다운 변환·PDF 출력 도구는 이 스크립트에서만 쓰므로 프로젝트 의존성에 넣지 않고 실행할 때만 불러온다(--with).
"""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "docs" / "label_agreement" / "rater_guide.md"
CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: 'Noto Sans CJK KR', 'Malgun Gothic', sans-serif; font-size: 10pt; line-height: 1.55; color: #1b1f24; }
h1 { font-size: 18pt; border-bottom: 2px solid #1f3a5f; padding-bottom: 6px; }
h2 { font-size: 13pt; color: #1f3a5f; margin-top: 18px; break-after: avoid; }
h3 { font-size: 11pt; margin-top: 14px; break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; font-size: 9pt; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border: 1px solid #c8cdd5; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #eef2f7; }
th:first-child, td:first-child { white-space: nowrap; }
blockquote { margin: 6px 0; padding: 6px 10px; background: #f6f8fa; border-left: 3px solid #1f3a5f; color: #444; }
pre { background: #f6f8fa; padding: 8px; font-size: 8.5pt; white-space: pre-wrap; break-inside: avoid; }
code { font-family: 'Noto Sans Mono CJK KR', monospace; font-size: 9pt; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 14px 0; }
"""


def render(out_dir: Path) -> Path:
    import markdown
    from playwright.sync_api import sync_playwright

    html = markdown.markdown(SRC.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
    page_html = f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "트리아지_판정_안내서.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(page_html, wait_until="load")
        page.pdf(path=str(out), format="A4", print_background=True,
                 display_header_footer=True, header_template="<span></span>",
                 footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#888'>"
                                 "<span class='pageNumber'></span> / <span class='totalPages'></span></div>",
                 margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        browser.close()
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="채점자 안내서 PDF 생성")
    p.add_argument("--out", type=Path, default=ROOT / "dist" / "label_agreement")
    print(f"저장: {render(p.parse_args(argv).out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
