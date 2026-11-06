"""EvidencePool 的契约级测试（Owner: B）。

验证四件事：
    1. chain 去重且保持首次命中顺序
    2. 每个解析出的 source_ref 都通过 source_ref 契约
    3. 未知 source_id 必须报错（不能静默跳过）
    4. 与 delivery_artifact 的 evidence_chain 字段兼容
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import evidence  # noqa: E402
import knowledge_hub as kh  # noqa: E402
from _schema import validator  # noqa: E402


@pytest.fixture(scope="module")
def chunks():
    return kh.build_index()


@pytest.fixture(scope="module")
def pool(chunks):
    return evidence.EvidencePool(chunks)


def test_chain_dedupes_and_keeps_order(pool):
    r1 = kh.retrieve("机器视觉 漏检率", chunks=pool._chunks, top_k=5)
    r2 = kh.retrieve("改造成本 回收", chunks=pool._chunks, top_k=5)
    first = pool.add_from_retrieval(r1)
    second = pool.add_from_retrieval(r2)

    chain = pool.to_chain()
    assert len(chain) == len(set(chain)), "chain 不允许重复"
    assert chain[: len(first)] == first, "顺序必须保持首次命中"
    assert set(chain) == set(first) | set(second)


def test_resolve_returns_valid_source_ref(pool):
    """每个 source_ref 都必须通过契约——位置字段与哈希格式最容易写错。"""
    r = kh.retrieve("合规 数据", chunks=pool._chunks, top_k=3)
    pool.add_from_retrieval(r)
    refs = pool.resolve_chain()
    assert refs, "至少应有一条证据"

    v = validator("source_ref.schema.json")
    for ref in refs:
        errors = list(v.iter_errors(ref))
        assert not errors, [f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors]


def test_unknown_source_id_raises(pool):
    with pytest.raises(evidence.EvidenceError):
        pool.add_from_retrieval({"query": "x", "mode": "bm25", "items": [{"source_id": "xx:not-exist", "score": 0.1}]})


def test_resolve_chain_rejects_missing(pool):
    with pytest.raises(evidence.EvidenceError):
        pool.resolve_chain(["kb:a1_gb_t_40659_2021_info", "mv:missing"])


def test_chain_compatible_with_delivery_artifact(chunks):
    """evidence_chain 直接塞进交付包时必须被接受。"""
    pool = evidence.EvidencePool(chunks)
    chain = evidence.build_chain([kh.retrieve("机器视觉", chunks=chunks, top_k=2)], chunks)
    artifact = {
        "solution": {"path": "solution.md", "sha256": "0" * 64},
        "evidence_chain": chain,
        "scorecard": {"run_id": "r", "metrics": {}, "issues": [], "verdict": "pass"},
        "trace_bundle": [],
        "manifest": {"genome_version": "0.1", "commit_sha": "1234567", "generated_at": "2026-11-05T00:00:00Z", "files": []},
    }
    errors = list(validator("delivery_artifact.schema.json").iter_errors(artifact))
    assert not errors, [f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors]


def test_refs_for_returns_all_chunks_of_doc(chunks):
    pool = evidence.EvidencePool(chunks)
    refs = pool.refs_for("kb:a1_gb_t_40659_2021_info")
    assert len(refs) >= 1
    assert {r["source_id"] for r in refs} == {"kb:a1_gb_t_40659_2021_info"}
    # 每段的字符区间必须落在该文件范围内且互不相同
    spans = [tuple(r["char_range"]) for r in refs]
    assert len(spans) == len(set(spans)), "同一文档的不同片段不应共用 char_range"
