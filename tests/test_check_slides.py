"""PPT 规格核验脚本的测试（Owner: B）。

核验脚本本身必须可信，否则"D 的 PPT 合格了"就是一句空话。
这里用 python-pptx **现场造一份符合官方规格的 PPT**，验证它判合格；
再造一份不合格的，验证它逐条报错。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_slides as cs  # noqa: E402

pptx = pytest.importorskip("pptx")


def _make_deck(path: Path, *, pages=13, size=(13.33, 7.5), font="思源黑体",
               title_size=32, info_size=20, section_size=24,
               cover_fields=("团队名称：某某队", "演讲人：某某",
                             "指导教师：某某", "学校：某某大学")):
    from pptx.util import Inches, Pt

    prs = pptx.Presentation()
    prs.slide_width = Inches(size[0])
    prs.slide_height = Inches(size[1])
    blank = prs.slide_layouts[6]

    # 封面
    cover = prs.slides.add_slide(blank)
    box = cover.shapes.add_textbox(Inches(0.6), Inches(0.6), Inches(10), Inches(1.2))
    run = box.text_frame.paragraphs[0].add_run()
    run.text = "链衡 ChainGuard"
    run.font.size = Pt(title_size)
    run.font.name = font

    info = cover.shapes.add_textbox(Inches(0.6), Inches(2.2), Inches(10), Inches(2))
    for i, line in enumerate(cover_fields):
        para = info.text_frame.paragraphs[0] if i == 0 else info.text_frame.add_paragraph()
        r = para.add_run()
        r.text = line
        r.font.size = Pt(info_size)
        r.font.name = font

    # 其余页
    for i in range(pages - 1):
        slide = prs.slides.add_slide(blank)
        tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.6), Inches(10), Inches(1))
        r = tb.text_frame.paragraphs[0].add_run()
        r.text = f"第 {i + 2} 页内容"
        r.font.size = Pt(section_size)
        r.font.name = font

    prs.save(str(path))
    return path


def test_compliant_deck_passes(tmp_path):
    path = _make_deck(tmp_path / "ok.pptx")
    assert cs.check(path) == []


def test_wrong_page_count_reported(tmp_path):
    path = _make_deck(tmp_path / "few.pptx", pages=6)
    problems = cs.check(path)
    assert any("页数" in p for p in problems)


def test_wrong_size_reported(tmp_path):
    path = _make_deck(tmp_path / "big.pptx", size=(16.67, 9.38))
    problems = cs.check(path)
    assert any("16:9" in p or "尺寸" in p for p in problems)


def test_wrong_font_reported(tmp_path):
    path = _make_deck(tmp_path / "yahei.pptx", font="Microsoft YaHei")
    problems = cs.check(path)
    assert any("思源黑体" in p for p in problems)


def test_wrong_title_size_reported(tmp_path):
    path = _make_deck(tmp_path / "small.pptx", title_size=28)
    problems = cs.check(path)
    assert any("32" in p for p in problems)


def test_missing_cover_fields_reported(tmp_path):
    path = _make_deck(tmp_path / "nocover.pptx", cover_fields=("团队名称：", "演讲人："))
    problems = cs.check(path)
    assert any("封面" in p for p in problems)


def test_secret_in_text_reported(tmp_path):
    path = _make_deck(tmp_path / "leak.pptx",
                      cover_fields=("团队名称：x", "演讲人：y", "指导教师：z", "学校：w",
                                    "api_key: sk-abcdefghijklmnop"))
    problems = cs.check(path)
    assert any("密钥" in p for p in problems)


def test_report_does_not_echo_personal_info(tmp_path, capsys):
    """报告只报"是否填写"，不回显人名/校名——仓库要转公开，日志不能泄露。"""
    path = _make_deck(tmp_path / "priv.pptx",
                      cover_fields=("团队名称：龙在飞", "演讲人：骆俊",
                                    "指导教师：石艳", "学校：岭南师范学院"))
    problems = cs.check(path)
    joined = "\n".join(problems)
    for token in ("龙在飞", "骆俊", "石艳", "岭南师范学院"):
        assert token not in joined, "核验输出泄露了个人信息"
