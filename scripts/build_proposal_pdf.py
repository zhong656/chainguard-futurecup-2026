"""把 `docs/方案书-正文.md` 导出为可提交的 PDF（Owner: B）。

路线：**Markdown → DOCX（python-docx，图片真正嵌入）→ Word COM 存为 PDF**

为什么不走 HTML
--------------
先试过 HTML → Word → PDF：Word 打开本地 HTML 时**不加载本地图片**
（页面只剩标题、图位空白），排查成本高且不可控。
改用 python-docx 直接生成 docx：图片作为内嵌对象，不依赖外部路径，
再由 Word 转 PDF——这是本机唯一稳定可控的路线（无 LibreOffice / reportlab）。

图片：仓库里是 SVG（矢量、浏览器好看），Word 不认，导出前用 Edge 渲染成 2 倍图 PNG。

用法
----
    python scripts/build_proposal_pdf.py
    python scripts/build_proposal_pdf.py --out x.pdf --keep-docx
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "方案书-正文.md"
DEFAULT_OUT = Path(r"D:\未来杯-ChainGuard\成片材料-20261111\方案书_链衡ChainGuard_v1.pdf")

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

HEI = "黑体"
SONG = "宋体"
MONO = "Consolas"


def _edge() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("[FAIL] 找不到 msedge.exe")


def rasterize(svg: Path, out_png: Path, scale: int = 2) -> Path:
    """SVG → 2 倍图 PNG（Word 不认 SVG）。"""
    if out_png.exists() and out_png.stat().st_size > 4096:
        return out_png
    text = svg.read_text(encoding="utf-8")
    width = int(re.search(r'width="(\d+)"', text).group(1))
    height = int(re.search(r'height="(\d+)"', text).group(1))
    subprocess.run(
        [_edge(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--window-size={width},{height}", f"--force-device-scale-factor={scale}",
         "--default-background-color=FFFFFFFF", f"--screenshot={out_png}",
         svg.resolve().as_uri()],
        check=False, capture_output=True,
    )
    if not out_png.exists() or out_png.stat().st_size < 4096:
        raise SystemExit(f"[FAIL] SVG 转 PNG 失败：{svg.name}")
    return out_png


def parse_blocks(md: str) -> list[tuple[str, object]]:
    """把 Markdown 拆成块。连续正文行**合并为一段**（否则会按行硬折）。"""
    lines = md.splitlines()
    blocks: list[tuple[str, object]] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue

        if s.startswith("```"):
            skip = i > 0 and "pdf-skip" in lines[i - 1]
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            if not skip:
                blocks.append(("code", "\n".join(code)))
            continue

        m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", s)
        if m:
            blocks.append(("image", (m.group(1), m.group(2))))
            i += 1
            continue

        if s.startswith("# "):
            blocks.append(("h1", s[2:].strip())); i += 1; continue
        if s.startswith("## "):
            blocks.append(("h2", s[3:].strip())); i += 1; continue
        if s.startswith("### "):
            blocks.append(("h3", s[4:].strip())); i += 1; continue

        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append(("quote", "\n".join(b for b in buf if b)))
            continue

        if s.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].strip()) <= set("|-: "):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            blocks.append(("table", rows))
            continue

        if s.startswith(("- ", "* ")) or re.match(r"^\d+\.\s", s):
            items = []
            while i < len(lines) and (lines[i].strip().startswith(("- ", "* "))
                                      or re.match(r"^\d+\.\s", lines[i].strip())):
                t = lines[i].strip()
                t = t[2:] if t.startswith(("- ", "* ")) else re.sub(r"^\d+\.\s", "", t)
                items.append(t)
                i += 1
            blocks.append(("list", items))
            continue

        if s in ("---", "***", "___"):
            blocks.append(("hr", "")); i += 1; continue

        buf = [s]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt:
                break
            if (nxt.startswith(("#", "|", ">", "- ", "* ", "```", "![", "---"))
                    or re.match(r"^\d+\.\s", nxt)):
                break
            buf.append(nxt)
            i += 1
        blocks.append(("para", "".join(buf)))
    return blocks


def _set_font(run, name: str, size: float, bold: bool = False, color=None):
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attr in ("w:eastAsia", "w:ascii", "w:hAnsi"):
        rfonts.set(qn(attr), name)


def _emit_inline(paragraph, text: str, base_font=SONG, base_size=10.5):
    from docx.shared import Pt

    for seg in re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text):
        if not seg:
            continue
        if seg.startswith("`") and seg.endswith("`") and len(seg) > 2:
            run = paragraph.add_run(seg[1:-1])
            _set_font(run, MONO, base_size - 1)
        elif seg.startswith("**") and seg.endswith("**") and len(seg) > 4:
            run = paragraph.add_run(seg[2:-2])
            _set_font(run, base_font, base_size, bold=True)
        else:
            run = paragraph.add_run(seg)
            _set_font(run, base_font, base_size)
    paragraph.paragraph_format.space_after = Pt(4)


def build_docx(md: str, out_docx: Path, image_dir: Path) -> Path:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.2)
    section.top_margin = section.bottom_margin = Cm(2.2)

    style = doc.styles["Normal"]
    style.font.name = SONG
    style.font.size = Pt(10.5)

    src_dir = DOC.parent
    for kind, payload in parse_blocks(md):
        if kind == "h1":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_font(p.add_run(str(payload)), HEI, 20, bold=True, color=(0x1B, 0x5E, 0x8C))
            p.paragraph_format.space_after = Pt(12)
        elif kind == "h2":
            p = doc.add_paragraph()
            _set_font(p.add_run(str(payload)), HEI, 14, bold=True, color=(0x1B, 0x5E, 0x8C))
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.keep_with_next = True
        elif kind == "h3":
            p = doc.add_paragraph()
            _set_font(p.add_run(str(payload)), HEI, 11.5, bold=True)
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
        elif kind == "para":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.first_line_indent = Pt(21)
            _emit_inline(p, str(payload))
        elif kind == "quote":
            for line in str(payload).splitlines():
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(0.6)
                _emit_inline(p, line, base_size=9.5)
        elif kind == "list":
            for item in payload:  # type: ignore[union-attr]
                p = doc.add_paragraph(style="List Bullet")
                _emit_inline(p, item, base_size=10.5)
        elif kind == "code":
            p = doc.add_paragraph()
            _set_font(p.add_run(str(payload)), MONO, 8.5)
            p.paragraph_format.left_indent = Cm(0.4)
            p.paragraph_format.space_after = Pt(6)
        elif kind == "table":
            rows = list(payload)  # type: ignore[arg-type]
            header = [c.strip() for c in rows[0].strip("|").split("|")]
            body = [[c.strip() for c in r.strip("|").split("|")] for r in rows[2:]]
            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for idx, text in enumerate(header):
                cell = table.rows[0].cells[idx]
                cell.text = ""
                _emit_inline(cell.paragraphs[0], text, base_font=HEI, base_size=9.5)
            for row in body:
                cells = table.add_row().cells
                for idx, text in enumerate(row[: len(header)]):
                    cells[idx].text = ""
                    _emit_inline(cells[idx].paragraphs[0], text, base_size=9.5)
            doc.add_paragraph().paragraph_format.space_after = Pt(2)
        elif kind == "image":
            alt, ref = payload  # type: ignore[misc]
            source = src_dir / ref
            png = rasterize(source, image_dir / (source.stem + ".png")) \
                if source.suffix.lower() == ".svg" else source
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(str(png), width=Cm(16))
            cap = doc.add_paragraph()
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_font(cap.add_run(f"图：{alt}"), SONG, 9, color=(0x5B, 0x67, 0x70))
        elif kind == "hr":
            p = doc.add_paragraph()
            _set_font(p.add_run(""), SONG, 4)

    doc.save(str(out_docx))
    return out_docx


def to_pdf(docx_path: Path, pdf_path: Path) -> None:
    import win32com.client as win32

    word = win32.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(str(docx_path.resolve()))
        doc.SaveAs2(str(pdf_path.resolve()), FileFormat=17)  # wdFormatPDF
        doc.Close(False)
    finally:
        word.Quit()


def verify(pdf_path: Path) -> int:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    han = len(re.findall(r"[\u4e00-\u9fff]", text))
    images = sum(len(page.images) for page in reader.pages)
    print(f"  · 页数 {len(reader.pages)}")
    print(f"  · 提取汉字 {han}")
    print(f"  · 图片对象 {images}")
    print(f"  · 体积 {pdf_path.stat().st_size / 1024:.0f} KB")

    required = ["选题背景", "平台总体架构", "Agent 角色定义", "调度算法",
                "结果验证策略", "核心代码模块", "测试用例", "人工智能使用说明"]
    missing = [r for r in required if r not in text]
    if missing:
        print(f"  [FAIL] PDF 缺少章节：{missing}")
        return 1
    if images < 5:
        print(f"  [FAIL] 图片只嵌入 {images} 个，应 ≥5")
        return 1
    if len(reader.pages) < 8:
        print("  [FAIL] 页数过少，排版异常")
        return 1
    print("  [PASS] 章节齐全、图片已嵌入")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--keep-docx", action="store_true")
    args = parser.parse_args()

    md = DOC.read_text(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cg-pdf-") as tmp:
        workdir = Path(tmp)
        docx_path = build_docx(md, workdir / "方案书.docx", workdir)
        print(f"[1/3] DOCX 生成：{docx_path.stat().st_size / 1024:.0f} KB")
        to_pdf(docx_path, args.out)
        print(f"[2/3] Word 导出 PDF：{args.out.name}")
        if args.keep_docx:
            keep = args.out.with_suffix(".docx")
            keep.write_bytes(docx_path.read_bytes())
            print(f"      DOCX 保留：{keep}")

    print("[3/3] 校验：")
    return verify(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
