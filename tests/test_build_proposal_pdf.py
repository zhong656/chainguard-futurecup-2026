"""方案书 PDF 导出脚本的测试（Owner: B）。

导出链路依赖本机 Word（CI 上没有），所以这里测**不依赖 Word 的部分**：
Markdown 解析与行内格式处理——它们出错会直接导致 PDF 内容缺章、段落折行、
表格串列，是最容易出问题的一环。

真实 PDF 的产出由 `python scripts/build_proposal_pdf.py` 端到端验证（输出页数/图片数/章节）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_proposal_pdf as b  # noqa: E402


def _kinds(blocks):
    return [k for k, _ in blocks]


def test_headings_parsed():
    blocks = b.parse_blocks("# 标题\n\n## 二级\n\n### 三级\n")
    assert _kinds(blocks) == ["h1", "h2", "h3"]
    assert blocks[0][1] == "标题"


def test_paragraph_lines_are_merged():
    """连续正文行必须合并成一段——否则导出后句子被硬折成两行。"""
    md = "第一行写了一半\n第二行接着写，应该和上面是一段。\n\n新段落。\n"
    blocks = b.parse_blocks(md)
    paras = [p for k, p in blocks if k == "para"]
    assert len(paras) == 2
    assert "第一行写了一半第二行接着写" in paras[0]


def test_table_parsed_with_rows():
    md = "| 维度 | 权重 |\n| --- | --- |\n| citation | 0.30 |\n| logic | 0.20 |\n"
    blocks = b.parse_blocks(md)
    assert _kinds(blocks) == ["table"]
    rows = blocks[0][1]
    assert len(rows) == 4  # 表头 + 分隔 + 2 行


def test_code_block_and_pdf_skip():
    md = "正常代码：\n\n```\nprint(1)\n```\n\n<!-- pdf-skip -->\n```\nASCII 图\n```\n"
    blocks = b.parse_blocks(md)
    codes = [p for k, p in blocks if k == "code"]
    assert len(codes) == 1, "pdf-skip 标注的代码块不应进入 PDF"
    assert "print(1)" in codes[0]


def test_image_block_captures_alt_and_path():
    blocks = b.parse_blocks("![系统架构](images/architecture.svg)\n")
    assert _kinds(blocks) == ["image"]
    alt, ref = blocks[0][1]
    assert alt == "系统架构"
    assert ref == "images/architecture.svg"


def test_list_block_collects_items():
    md = "- 第一条\n- 第二条\n\n1. 有序一\n2. 有序二\n"
    blocks = b.parse_blocks(md)
    lists = [p for k, p in blocks if k == "list"]
    assert len(lists) == 2
    assert lists[0] == ["第一条", "第二条"]
    assert lists[1] == ["有序一", "有序二"]


def test_quote_block():
    blocks = b.parse_blocks("> 引用第一行\n> 引用第二行\n")
    assert _kinds(blocks) == ["quote"]
    assert "引用第一行" in str(blocks[0][1])


def test_hr_recognized():
    blocks = b.parse_blocks("段一\n\n---\n\n段二\n")
    assert "hr" in _kinds(blocks)


def test_proposal_covers_all_eight_official_parts():
    """真实方案书解析后，八个官方部分都必须出现（防止导出时丢章）。"""
    md = (ROOT / "docs" / "方案书-正文.md").read_text(encoding="utf-8")
    blocks = b.parse_blocks(md)
    headings = " ".join(str(p) for k, p in blocks if k == "h2")
    for key in ("选题背景", "平台总体架构", "Agent 角色定义", "调度算法",
                "结果验证策略", "核心代码模块", "测试用例", "人工智能使用说明"):
        assert key in headings, f"二级标题缺少：{key}"


def test_images_in_proposal_exist_on_disk():
    md = (ROOT / "docs" / "方案书-正文.md").read_text(encoding="utf-8")
    for kind, payload in b.parse_blocks(md):
        if kind == "image":
            _, ref = payload
            assert (ROOT / "docs" / ref).exists(), f"图片不存在：{ref}"
