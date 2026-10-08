"""v1.5 라벨 일치율 — 채점자용 판정 시트(엑셀)와 번호 대응표를 만든다.

계획: report/label_agreement_v15_plan.md · 채점자 안내서: docs/label_agreement/rater_guide.md

사용법
------
    uv run python tools/label_agreement/build_sheets.py            # dist/label_agreement/ 에 시트 2개
    uv run python tools/label_agreement/build_sheets.py --out <폴더>

출력
----
    <out>/트리아지_판정시트_채점자1.xlsx, <out>/트리아지_판정시트_채점자2.xlsx   채점자에게 보내는 파일
    data/label_agreement/blind_map_v15.json                                     번호(Q01~Q63) → 문항 ID 대응표

[설계 의도]
1. 시트에는 모델이 받는 입력과 같은 내용만 넣는다(입력 종류·게시판/작성자·게시 일시·제목·본문·업데이트 공지·기존 등록 이슈).
   정답 라벨, 판정 근거(rationale), 세트·제보 품질·위험 표시, 원래 문항 ID는 넣지 않는다. 채점자가 기존 판정을 따라가지 않게 하기 위해서다.
2. 문항 ID(A01·B01·S01)는 트랙과 집중 세트(판정이 까다로운 문항)를 드러내므로, 고정 seed로 섞은 뒤 Q01~Q63으로 다시 번호를 붙인다.
   대응표는 저장소에 남기고 채점자에게는 보내지 않는다. 같은 seed면 언제 만들어도 같은 순서가 나온다.
3. 두 채점자의 시트는 문항 순서와 구성이 같다. 파일 이름의 채점자 번호만 다르다.
4. 고르는 칸은 드롭다운으로만 받는다. 선택지는 출력 형식 v2(contract.py)의 허용 값을 그대로 쓰므로, 받은 답을 모델 응답과 같은
   채점 함수(score.field_correct)로 대조할 수 있다. 모듈은 모듈1(필수)·모듈2(선택)로 받아 " / "로 합친다.
5. 진행률은 수식으로 계산한다(시작하기 탭). 6칸이 모두 채워진 문항 수 / 63.
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from triage_eval.common.paths import ROOT
from triage_eval.pipeline.contract import ENUMS_V2, MODULES, NO_MODULE
from triage_eval.pipeline.prompt import TRACK_LABEL

DATASET = ROOT / "data" / "eval_v14" / "aether_raid_v14.json"
MAP_PATH = ROOT / "data" / "label_agreement" / "blind_map_v15.json"
DEFAULT_OUT = ROOT / "dist" / "label_agreement"
SEED = 1505
RATERS = ["채점자1", "채점자2"]

INPUT_COLS = ["번호", "입력 종류", "게시판 / 작성자", "게시 일시", "제목", "본문", "참고: 업데이트 공지", "참고: 기존 등록 이슈"]
ANSWER_COLS = ["분류", "모듈1", "모듈2 (선택)", "우선순위", "재현 정보", "발생 빈도", "처리"]
EXTRA_COLS = ["확신도", "메모"]
REQUIRED = ["분류", "모듈1", "우선순위", "재현 정보", "발생 빈도", "처리"]
CONFIDENCE = ["높음", "보통", "낮음"]
CHOICES = {
    "분류": ENUMS_V2["분류"],
    "모듈1": MODULES + [NO_MODULE],
    "모듈2 (선택)": MODULES,
    "우선순위": ENUMS_V2["우선순위"],
    "재현 정보": ENUMS_V2["재현 정보"],
    "발생 빈도": ENUMS_V2["발생 빈도"],
    "처리": ENUMS_V2["처리"],
    "확신도": CONFIDENCE,
}
EXAMPLES = [   # docs/label_agreement/rater_guide.md 5절과 같은 예시 (평가셋과 겹치지 않는 가상 리포트, docs/method/m1_examples.md E2·E3)
    {"번호": "예시1", "입력 종류": TRACK_LABEL["A"], "게시판 / 작성자": "자유게시판", "게시 일시": "2026-08-05 22:41",
     "제목": "낚시하면 멈춤", "본문": "낚시만 하면 화면 멈춰요", "참고: 업데이트 공지": "", "참고: 기존 등록 이슈": "",
     "분류": "결함", "모듈1": "클라이언트 안정성", "모듈2 (선택)": "", "우선순위": "판단보류", "재현 정보": "부족",
     "발생 빈도": "미기재", "처리": "정보 요청 후 보류", "확신도": "보통",
     "메모": "기기·장소 없음(R-3). 멈춤은 Critical 가능 현상이지만 정보 부족 → 판단보류 + 정보 요청(H-3a)"},
    {"번호": "예시2", "입력 종류": TRACK_LABEL["B"], "게시판 / 작성자": "내부 QA", "게시 일시": "",
     "제목": "[UI] 우편함 닫기 버튼 아이콘이 2px 왼쪽으로 어긋남",
     "본문": "[테스트 환경]\nPC / 빌드 2.3.0.1544 (QA 빌드)\n\n[재현율]\n10/10 (100%)\n\n[이슈 설명]\n우편함 창 오른쪽 위 닫기(X) 버튼의 "
             "아이콘이 버튼 영역 중앙에서 왼쪽으로 2px 치우쳐 표시됨. 버튼 입력은 정상.\n\n[기대 결과]\n아이콘이 버튼 영역 중앙에 표시된다.\n\n"
             "[실제 결과]\n아이콘이 왼쪽으로 2px 치우침. 클릭·터치 영역은 정상.",
     "참고: 업데이트 공지": "", "참고: 기존 등록 이슈": "",
     "분류": "결함", "모듈1": "UI·텍스트", "모듈2 (선택)": "", "우선순위": "Trivial", "재현 정보": "충분",
     "발생 빈도": "항상", "처리": "개발 배정", "확신도": "높음", "메모": ""},
]

FONT = "맑은 고딕"
F_BASE, F_BOLD = Font(name=FONT, size=10), Font(name=FONT, size=10, bold=True)
F_TITLE, F_HEAD = Font(name=FONT, size=16, bold=True), Font(name=FONT, size=10, bold=True, color="FFFFFF")
FILL_HEAD = PatternFill("solid", fgColor="1F3A5F")
FILL_INPUT = PatternFill("solid", fgColor="F2F4F7")
FILL_ANSWER = PatternFill("solid", fgColor="FFF2CC")
FILL_EXTRA = PatternFill("solid", fgColor="E2EFDA")
THIN = Side(style="thin", color="C8CDD5")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP_TOP = Alignment(wrap_text=True, vertical="top")
WIDTHS = {"번호": 7, "입력 종류": 14, "게시판 / 작성자": 14, "게시 일시": 11, "제목": 26, "본문": 60,
          "참고: 업데이트 공지": 22, "참고: 기존 등록 이슈": 30, "분류": 11, "모듈1": 15, "모듈2 (선택)": 15,
          "우선순위": 10, "재현 정보": 9, "발생 빈도": 10, "처리": 16, "확신도": 8, "메모": 34}


def dev_items(dataset: dict) -> list[dict]:
    return [i for i in dataset["items"] if i["split"] == "dev"]


def blind_order(items: list[dict], seed: int = SEED) -> list[tuple[str, dict]]:
    """설계 의도 2 — 고정 seed로 섞고 Q01~ 번호를 붙인다."""
    shuffled = sorted(items, key=lambda i: i["id"])
    random.Random(seed).shuffle(shuffled)
    return [(f"Q{n:02d}", item) for n, item in enumerate(shuffled, start=1)]


def row_of(qid: str, item: dict) -> dict:
    """설계 의도 1 — 모델 입력과 같은 정보만."""
    inp, ctx = item["input"], item["input"].get("context", {})
    a = item["track"] == "A"
    return {"번호": qid, "입력 종류": TRACK_LABEL[item["track"]],
            "게시판 / 작성자": inp["board"] if a else inp["reporter"], "게시 일시": inp["posted_at"] if a else "",
            "제목": inp["title"], "본문": inp["body"], "참고: 업데이트 공지": ctx.get("update_note", ""),
            "참고: 기존 등록 이슈": "\n".join(f"- {k}" for k in ctx.get("known_issues", []))}


def sheet_height(row: dict) -> float:
    lines = max(row["본문"].count("\n") + 1 + len(row["본문"]) // 55, row["참고: 기존 등록 이슈"].count("\n") * 2 + 2, 3)
    return min(15 * lines, 409)


def write_table(ws, rows: list[dict], with_validation: bool, choices_ref: dict[str, str]):
    cols = INPUT_COLS + ANSWER_COLS + EXTRA_COLS
    for c, name in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font, cell.fill, cell.alignment, cell.border = F_HEAD, FILL_HEAD, Alignment(wrap_text=True, vertical="center"), BORDER
        ws.column_dimensions[cell.column_letter].width = WIDTHS[name]
    ws.row_dimensions[1].height = 30
    for r, row in enumerate(rows, start=2):
        for c, name in enumerate(cols, start=1):
            cell = ws.cell(row=r, column=c, value=row.get(name, "") or None)
            cell.font, cell.alignment, cell.border = F_BASE, WRAP_TOP, BORDER
            cell.fill = FILL_INPUT if name in INPUT_COLS else FILL_ANSWER if name in ANSWER_COLS else FILL_EXTRA
        ws.row_dimensions[r].height = sheet_height(row)
    ws.freeze_panes = "C2"
    if with_validation:
        last = len(rows) + 1
        for c, name in enumerate(cols, start=1):
            if name in choices_ref:
                dv = DataValidation(type="list", formula1=choices_ref[name], allow_blank=True, showDropDown=False,
                                    showErrorMessage=True, errorTitle="선택지에서 골라 주세요",
                                    error="드롭다운의 선택지 중 하나를 골라 주세요. 애매하면 가장 가까운 값을 고르고 메모에 적어 주세요.")
                ws.add_data_validation(dv)
                letter = ws.cell(row=1, column=c).column_letter
                dv.add(f"{letter}2:{letter}{last}")


def write_choices(ws) -> dict[str, str]:
    """선택지 탭 — 드롭다운 목록과 칸별 짧은 설명. {칸: 목록 범위 수식}."""
    refs = {}
    for c, (name, values) in enumerate(CHOICES.items(), start=1):
        head = ws.cell(row=1, column=c, value=name)
        head.font, head.fill, head.border = F_HEAD, FILL_HEAD, BORDER
        for r, v in enumerate(values, start=2):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font, cell.border = F_BASE, BORDER
        letter = head.column_letter
        ws.column_dimensions[letter].width = 17
        refs[name] = f"=선택지!${letter}$2:${letter}${len(values) + 1}"
    note = ws.cell(row=1, column=len(CHOICES) + 2, value="이 탭은 드롭다운 목록입니다. 수정하지 말아 주세요. 각 값의 기준은 안내서 4절에 있습니다.")
    note.font = F_BOLD
    return refs


def write_start(ws, n: int, rater: str):
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 80
    ws["A1"] = "버그 리포트 1차 트리아지 판정 시트"
    ws["A1"].font = F_TITLE
    ws["A2"] = f"{rater} · 리포트 {n}건 · 함께 드린 「판정 안내서」를 기준으로 판정합니다"
    ws["A2"].font = F_BASE
    rows = [
        ("진행 순서", "① 안내서 3·4절 읽기 → ② '작성 예시' 탭 보기 → ③ '판정' 탭에서 Q01부터 노란 칸 6개 고르기 → ④ 아래 진행률 100% 확인 후 파일 그대로 보내기"),
        ("노란 칸 (필수)", "분류 · 모듈1 · 우선순위 · 재현 정보 · 발생 빈도 · 처리 — 드롭다운에서 하나씩 고릅니다"),
        ("노란 칸 (선택)", "모듈2 — 두 모듈이 함께 걸릴 때만 고르고, 하나면 비워 둡니다"),
        ("초록 칸 (선택)", "확신도(높음·보통·낮음), 메모 — 고민한 문항은 확신도 '낮음'과 이유 한 줄을 남겨 주세요"),
        ("회색 칸", "리포트 내용입니다. 고치지 말아 주세요"),
        ("지켜 주실 것", "혼자 판정 · 다른 채점자와 상의하지 않기 · 안내서 외의 자료(검색·AI·프로젝트 저장소) 보지 않기 · 리포트에 적힌 내용만으로 판정"),
    ]
    for r, (k, v) in enumerate(rows, start=4):
        ws.cell(row=r, column=1, value=k).font = F_BOLD
        cell = ws.cell(row=r, column=2, value=v)
        cell.font, cell.alignment = F_BASE, Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 30
    r = len(rows) + 5
    last = n + 1
    ws.cell(row=r, column=1, value="진행률 (6칸 모두 채운 문항)").font = F_BOLD
    cond = "*".join(f'(판정!{col}2:{col}{last}<>"")' for col in ("I", "J", "L", "M", "N", "O"))
    prog = ws.cell(row=r, column=2, value=f"=SUMPRODUCT({cond})/{n}")
    prog.number_format, prog.font = "0%", Font(name=FONT, size=14, bold=True)
    ws.cell(row=r + 1, column=1, value="채운 문항 수").font = F_BOLD
    ws.cell(row=r + 1, column=2, value=f"=SUMPRODUCT({cond})").font = F_BASE


def build(out_dir: Path, map_path: Path = MAP_PATH) -> list[Path]:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    order = blind_order(dev_items(dataset))
    rows = [row_of(q, item) for q, item in order]
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(json.dumps({
        "seed": SEED, "dataset": "data/eval_v14/aether_raid_v14.json", "dataset_version": dataset["version"],
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "map": {q: item["id"] for q, item in order}}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for rater in RATERS:
        wb = Workbook()
        start = wb.active
        start.title = "시작하기"
        judge, example, choices = wb.create_sheet("판정"), wb.create_sheet("작성 예시"), wb.create_sheet("선택지")
        refs = write_choices(choices)
        write_table(judge, rows, with_validation=True, choices_ref=refs)
        write_table(example, EXAMPLES, with_validation=False, choices_ref=refs)
        write_start(start, len(rows), rater)
        path = out_dir / f"트리아지_판정시트_{rater}.xlsx"
        wb.save(path)
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v1.5 라벨 일치율 판정 시트 생성")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    for path in build(args.out):
        print(f"저장: {path}")
    print(f"번호 대응표: {MAP_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
