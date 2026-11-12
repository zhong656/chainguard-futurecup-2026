"""方案讲解 PPT 的规格核验（Owner: B，Issue #88 验收用）。

官方要求：正文 10~15 页、必须用组委会模板（思源黑体 32/20/24 号、16:9）。
人工目测"套没套模板"不可靠——这里直接用 python-pptx 读文件核。

检查项
------
1. 页数 12~15（封面 + 正文 + 末页；官方"正文 10~15"留一次缓冲）
2. 尺寸 13.33 × 7.50 英寸（16:9）
3. P1 四个占位字段均已填写（团队/演讲人/指导教师/学校）
4. 标题字号 32、信息行 20、内容页小标题 24
5. 字体名含思源黑体（Source Han Sans）
6. 无密钥字符串

**人名与校名只在报告里显示"已填写/未填写"，不打印具体内容**——
仓库要转公开，输出不能落到日志里。

用法：
    python scripts/check_slides.py "D:\\...\\路演PPT_v6.pptx"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MIN_PAGES, MAX_PAGES = 12, 15
EXPECT_W_IN, EXPECT_H_IN = 13.33, 7.50
EXPECT_EMU = 914400  # 1 英寸

TITLE_SIZE = 32
INFO_SIZE = 20
SECTION_SIZE = 24

CJK_FONT_HINTS = ("思源黑体", "Source Han Sans", "Noto Sans CJK")
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{16,}|api[_-]?key\s*[:=]", re.I)

P1_FIELDS = ("团队名称", "演讲人", "指导教师", "学校")


def _slides(path: Path):
    from pptx import Presentation

    return Presentation(str(path))


def _all_text(prs) -> str:
    chunks = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                chunks.append(shape.text_frame.text)
    return "\n".join(chunks)


def _runs(slide):
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                if run.text.strip():
                    yield run


def _size(run):
    return run.font.size.pt if run.font.size is not None else None


def check(path: Path) -> list[str]:
    """返回问题列表；空列表表示合格。"""
    problems: list[str] = []
    prs = _slides(path)

    pages = len(prs.slides)
    if not (MIN_PAGES <= pages <= MAX_PAGES):
        problems.append(f"页数 {pages} 不在 {MIN_PAGES}–{MAX_PAGES} 范围内")

    w_in, h_in = prs.slide_width / EXPECT_EMU, prs.slide_height / EXPECT_EMU
    if abs(w_in - EXPECT_W_IN) > 0.05 or abs(h_in - EXPECT_H_IN) > 0.05:
        problems.append(f"尺寸 {w_in:.2f}×{h_in:.2f} 英寸，应为 {EXPECT_W_IN}×{EXPECT_H_IN}（16:9）")

    # 封面四个字段：只报"是否填写"，不回显内容
    cover_text = "\n".join(
        sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame
    ) if pages else ""
    for field in P1_FIELDS:
        if field not in cover_text:
            problems.append(f"封面缺少字段：{field}")
        else:
            line = next((l for l in cover_text.splitlines() if field in l), "")
            value = re.sub(rf".*{field}\s*[:：]\s*", "", line).strip()
            if not value or value in {"（", ")", "/", "-"}:
                problems.append(f"封面字段未填写：{field}")

    # 字号与字体
    sizes = {_size(run) for slide in prs.slides for run in _runs(slide)}
    if TITLE_SIZE not in sizes:
        problems.append(f"未找到标题字号 {TITLE_SIZE}（封面题目）")
    if INFO_SIZE not in sizes:
        problems.append(f"未找到信息行字号 {INFO_SIZE}（封面团队/学校等）")
    if SECTION_SIZE not in sizes:
        problems.append(f"未找到内容页小标题字号 {SECTION_SIZE}")

    fonts = {run.font.name for slide in prs.slides for run in _runs(slide) if run.font.name}
    if not any(any(h in (f or "") for h in CJK_FONT_HINTS) for f in fonts):
        problems.append(f"未使用思源黑体（实际字体：{sorted(f for f in fonts if f)[:4]}）")

    # 密钥
    if SECRET_PATTERN.search(_all_text(prs)):
        problems.append("PPT 文本中出现疑似密钥字符串")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="方案讲解 PPT 规格核验")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if not args.path.exists():
        print(f"[FAIL] 文件不存在：{args.path}")
        return 1

    prs = _slides(args.path)
    print(f"文件：{args.path.name}")
    print(f"  · 页数 {len(prs.slides)}")
    print(f"  · 尺寸 {prs.slide_width / EXPECT_EMU:.2f} × {prs.slide_height / EXPECT_EMU:.2f} 英寸")

    problems = check(args.path)
    if problems:
        print("\n[FAIL] 规格不合格：")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\n[PASS] 规格合格（页数/尺寸/封面字段/字号/字体/无密钥）")
    print("       仍需人工确认：P5 合规提示（无国家领导人照片、无国家地图）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
