"""材料组装门禁的测试（Owner: B，A 在 #87 review 里要求）。

A 指出的问题：旧版组装脚本**缺必交材料或选中超时视频时仍 exit 0**，
等于生成了一个"看起来能交"的目录。这类假绿比报错更危险。

这里用临时目录造各种残缺输入，逐项确认门禁会拦，并且**返回非零**。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import assemble_materials as am  # noqa: E402

pytest.importorskip("pptx", reason="构造测试用 PPT 需要 python-pptx")
pytest.importorskip("pypdf", reason="校验 PDF 字数需要 pypdf")


def _fake_pdf(path: Path, han: int) -> Path:
    """造一个能被 pypdf 抽到 han 个汉字的 PDF。

    注意两点（都踩过）：
      1. 默认字体不支持中文 → 用 pymupdf 内置 `china-s`；
      2. 单页塞几千字会被裁掉 → **按每页 700 字分页**。
    """
    import pymupdf

    doc = pymupdf.open()
    remaining = han
    while remaining > 0:
        page = doc.new_page()
        chunk = min(remaining, 700)
        page.insert_text((60, 80), "方案书内容" * (chunk // 5 + 1),
                         fontname="china-s", fontsize=10)
        remaining -= chunk
    doc.save(str(path))
    doc.close()
    return path


def _fake_pptx(path: Path, pages: int, size=(13.33, 7.5)) -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(size[0])
    prs.slide_height = Inches(size[1])
    for _ in range(pages):
        prs.slides.add_slide(prs.slide_layouts[6])
    prs.save(str(path))
    return path


def test_gate_reports_all_missing(tmp_path):
    problems = am.gate(tmp_path)
    joined = " ".join(problems)
    assert "方案书" in joined and "PPT" in joined and "视频" in joined


def test_gate_rejects_low_resolution_video(tmp_path, monkeypatch):
    video = tmp_path / "演示视频.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(am, "probe_video", lambda p: {"width": 960, "height": 544, "duration": 270})
    problems = am.gate(tmp_path)
    assert any("1080" in p or "分辨率" in p for p in problems)


def test_gate_rejects_over_length_video(tmp_path, monkeypatch):
    (tmp_path / "演示视频.mp4").write_bytes(b"x")
    monkeypatch.setattr(am, "probe_video", lambda p: {"width": 1920, "height": 1080, "duration": 393})
    problems = am.gate(tmp_path)
    assert any("时长" in p for p in problems)


def test_gate_rejects_short_pdf(tmp_path, monkeypatch):
    _fake_pdf(tmp_path / "方案书_x.pdf", han=100)
    (tmp_path / "演示视频.mp4").write_bytes(b"x")
    _fake_pptx(tmp_path / "路演PPT_v1.pptx", pages=14)
    monkeypatch.setattr(am, "probe_video", lambda p: {"width": 1920, "height": 1080, "duration": 270})
    problems = am.gate(tmp_path)
    assert any("5000" in p or "汉字" in p for p in problems)


def test_gate_accepts_complete_set(tmp_path, monkeypatch):
    _fake_pdf(tmp_path / "方案书_x.pdf", han=5200)
    (tmp_path / "演示视频.mp4").write_bytes(b"x")
    _fake_pptx(tmp_path / "路演PPT_final.pptx", pages=14)
    monkeypatch.setattr(am, "probe_video", lambda p: {"width": 1920, "height": 1080, "duration": 270})
    assert am.gate(tmp_path) == []


def test_assemble_returns_nonzero_when_gate_fails(tmp_path, monkeypatch):
    """A 的核心要求：缺材料时**不能 exit 0**。"""
    monkeypatch.setattr(am, "gate", lambda m: ["缺少方案书 PDF"])
    code = am.assemble(tmp_path, tmp_path / "out", "1.0")
    assert code == 1, "门禁失败时必须返回非零"


def test_assemble_exit_nonzero_really(tmp_path, monkeypatch):
    """不经 monkeypatch：空目录真跑一遍，确认真实退出码非零。"""
    empty = tmp_path / "materials"
    empty.mkdir()
    assert am.assemble(empty, tmp_path / "out2", "1.0") == 1
    assert not (tmp_path / "out2").exists(), "门禁失败时不应创建输出目录"
