"""页码链路测试（Owner: B）。

目标：让 `source_ref.page` 有真实来源，同时**不给纯文本编假页码**。

链路是：解析层（parse）→ Chunk.page → evidence._to_ref["page"]。
本文件锁三件事：
    1. Markdown/纯文本 → page 为 None（诚实标注，不编页码）；
    2. 分页文档的 Chunk 带页码时 → source_ref.page 透传；
    3. char_range 的语义随格式不同（页内偏移 vs 文件偏移），不能混用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import evidence  # noqa: E402
import knowledge_hub as kh  # noqa: E402


def test_text_corpus_has_no_fake_page_numbers():
    """当前 17 份语料是 Markdown 转述卡：没有物理页，page 必须是 None。"""
    chunks = kh.build_index()
    assert chunks, "索引不应为空"
    assert all(c.page is None for c in chunks), "纯文本不应出现页码"


def test_source_ref_page_is_none_for_text():
    pool = evidence.EvidencePool(kh.build_index())
    sid = pool.all_source_ids()[0] if hasattr(pool, "all_source_ids") else None
    if sid is None:  # 没有便捷方法时退回直接取一片
        sid = kh.build_index()[0].source_id
    ref = pool.refs_for(sid)[0]
    assert ref["page"] is None
    assert ref["char_range"][0] < ref["char_range"][1]


def test_paginated_chunk_carries_page_through_to_source_ref():
    """构造一个带页码的 Chunk，验证证据链把它原样带出去。"""
    chunk = kh.Chunk(
        source_id="kb:a1_gb_t_40659_2021_info",
        doc_id="a1_gb_t_40659_2021_info",
        path="corpus/demo.pdf",
        start=0,
        end=12,
        text="标准正文第一页示例",
        hash="deadbeef",
        page=3,
    )
    pool = evidence.EvidencePool([chunk])
    ref = pool.refs_for("kb:a1_gb_t_40659_2021_info")[0]
    assert ref["page"] == 3, "页码必须从 Chunk 透传到 source_ref"
    assert ref["char_range"] == [0, 12]


def test_paginated_branch_is_wired_for_pdf(tmp_path):
    """PDF 走解析层；没装 pymupdf 时应报可执行的依赖提示，而不是当成空文件跳过。"""
    fake = tmp_path / "demo.pdf"
    fake.write_bytes(b"%PDF-1.4 fake")
    try:
        import pymupdf  # noqa: F401, PLC0415
    except ImportError:
        from src.tools import parse  # noqa: PLC0415

        with pytest.raises(parse.DependencyError):
            parse.parse_document(fake)
    else:  # pragma: no cover
        pytest.skip("已安装 pymupdf，跳过缺依赖用例")

def test_evidence_refs_are_shipped_in_package(tmp_path):
    """交付包必须带 evidence_refs.json：只有 id 的话，"引了哪段原文"无从核对。"""
    import json
    import vertical_slice

    vertical_slice.run_vertical_slice("用机器视觉升级精密零件产线质检", output=tmp_path)

    refs = json.loads((tmp_path / "evidence_refs.json").read_text(encoding="utf-8"))
    assert refs, "证据引用不应为空"
    for ref in refs:
        for key in ("source_id", "file_path", "page", "char_range", "text", "hash"):
            assert key in ref, f"source_ref 缺字段 {key}"
        assert ref["char_range"][0] < ref["char_range"][1]

    artifact = json.loads((tmp_path / "delivery_artifact.json").read_text(encoding="utf-8"))
    paths = [f["path"] for f in artifact["manifest"]["files"]]
    assert "evidence_refs.json" in paths, "证据引用文件必须进 manifest，否则可被悄悄替换"
