"""文档解析的边界测试（Owner: B）。

重点不是"能读 md"，而是：
    1. 页信息保留（证据链的 page 字段靠它）
    2. 空文件 / 扫描版 PDF 必须**报错**，不能返回空字符串假装成功
    3. 缺可选依赖时报可执行的提示，不是裸 ImportError
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tools import parse  # noqa: E402


def test_markdown_parsed_with_synthetic_page(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# 标题\n\n第一段。\n\n第二段。\n", encoding="utf-8")
    doc = parse.parse_document(p)
    assert doc.kind == "md"
    assert doc.page_count == 0, "Markdown 没有物理页，不应谎报页码"
    assert doc.pages[0].synthetic is True
    assert "第一段" in doc.text and "第二段" in doc.text


def test_txt_parsed(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("纯文本内容", encoding="utf-8")
    doc = parse.parse_document(p)
    assert doc.kind == "txt"
    assert doc.text == "纯文本内容"


def test_whitespace_collapsed(tmp_path):
    """PDF 常见多余空行要压掉，但段落分隔要保留。"""
    p = tmp_path / "a.txt"
    p.write_text("甲   \n\n\n\n乙\n", encoding="utf-8")
    doc = parse.parse_document(p)
    assert doc.text == "甲\n\n乙"


def test_empty_file_raises(tmp_path):
    p = tmp_path / "empty.md"
    p.write_text("   \n\n  ", encoding="utf-8")
    with pytest.raises(parse.ParseError):
        parse.parse_document(p)


def test_unsupported_suffix_raises(tmp_path):
    p = tmp_path / "a.xlsx"
    p.write_bytes(b"\x00")
    with pytest.raises(parse.ParseError) as exc:
        parse.parse_document(p)
    assert "不支持" in str(exc.value)


def test_missing_file_raises(tmp_path):
    with pytest.raises(parse.ParseError):
        parse.parse_document(tmp_path / "nope.md")


def test_pdf_without_dependency_gives_actionable_error(tmp_path):
    """没装 pymupdf 时应给 pip install 提示，而不是裸 ImportError。"""
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    try:
        import pymupdf  # noqa: F401, PLC0415
    except ImportError:
        with pytest.raises(parse.DependencyError) as exc:
            parse.parse_document(p)
        assert "pip install" in str(exc.value)
    else:  # pragma: no cover
        pytest.skip("已安装 pymupdf，跳过缺依赖用例")


def test_parse_corpus_collects_errors(tmp_path):
    (tmp_path / "good.md").write_text("正常内容", encoding="utf-8")
    (tmp_path / "bad.md").write_text("   ", encoding="utf-8")
    docs, errors = parse.parse_corpus(tmp_path, skip_errors=True)
    assert len(docs) == 1
    assert len(errors) == 1
    assert "bad.md" in errors[0]


def test_parse_corpus_fails_fast_by_default(tmp_path):
    (tmp_path / "bad.md").write_text("   ", encoding="utf-8")
    with pytest.raises(parse.ParseError):
        parse.parse_corpus(tmp_path)


def test_real_corpus_parses():
    """仓库自带的 5 篇语料必须都能解析——这是入库链路的前提。"""
    docs, errors = parse.parse_corpus(ROOT / "knowledge" / "corpus")
    assert not errors, errors
    assert len(docs) >= 5
    assert all(doc.text for doc in docs)
