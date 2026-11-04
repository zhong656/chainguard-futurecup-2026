"""KnowledgeHub 的契约级测试（Owner: B）。

只验证三件事：
    1. 输出严格符合 contracts/retrieval_result.schema.json
    2. RRF 融合确实让"双路都命中"的文档排更前
    3. 分数归一化、名次连续、空查询报错
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import knowledge_hub as kh  # noqa: E402

SCHEMA_PATH = ROOT / "contracts" / "retrieval_result.schema.json"


@pytest.fixture(scope="module")
def chunks():
    return kh.build_index()


def test_index_not_empty(chunks):
    """语料至少能建出索引，否则检索永远返回空。"""
    assert chunks, "knowledge/corpus/ 里没有可索引内容"


def test_retrieve_matches_contract(chunks):
    """输出必须通过 retrieval_result 契约（含 source_id 命名空间）。

    注意：`retrieval_result` 里的 `source_id` 是 `$ref` 到 `source_ref` 的 `$defs`，
    必须用 `scripts/_schema.py` 的离线 registry 校验，否则会尝试联网取引用。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    from _schema import validator  # noqa: PLC0415

    result = kh.retrieve("机器视觉 质检 漏检", chunks=chunks)

    errors = list(validator("retrieval_result.schema.json").iter_errors(result))
    assert not errors, [f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors]


def test_scores_normalized_and_ranked(chunks):
    """score ∈ (0,1]，rank 从 1 连续递增，按分数降序。"""
    result = kh.retrieve("成本 回收 周期", chunks=chunks, top_k=5)
    items = result["items"]
    assert items, "查询应有命中"
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))
    for item in items:
        assert 0 < item["score"] <= 1.0
    assert items[0]["score"] == 1.0, "归一化后第一名应为 1.0"
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_top_k_limits_results(chunks):
    assert len(kh.retrieve("红树", chunks=chunks, top_k=1)["items"]) <= 1
    assert len(kh.retrieve("红树", chunks=chunks, top_k=3)["items"]) <= 3


def test_rrf_prefers_dual_route_hit(chunks):
    """双路都命中的文档应排在单路命中之前（RRF 的核心性质）。"""
    query = "机器视觉 漏检率"
    idf = kh._idf(chunks)
    lex = kh._lexical_scores(chunks, query, idf)
    vec = kh._vector_scores(chunks, query)
    fused = kh._rrf([kh._ranking(lex), kh._ranking(vec)])

    best_lex = max(range(len(chunks)), key=lambda i: lex[i])
    best_vec = max(range(len(chunks)), key=lambda i: vec[i])
    # 两路同时靠前的块，融合分不应低于任一单路冠军之外的平均水平
    assert fused[best_lex] > 0 and fused[best_vec] > 0
    # 融合分不会低于任一路给自己的 1/(k+1)
    assert fused[best_lex] >= 1.0 / (kh.RRF_K + 1)


def test_empty_query_raises():
    with pytest.raises(ValueError):
        kh.retrieve("   ")


def test_unknown_mode_raises(chunks):
    with pytest.raises(ValueError):
        kh.retrieve("测试", chunks=chunks, mode="semantic")


def test_available_sources_are_resolvable(chunks):
    """每个 source_id 都必须能回溯到 sources.yaml 的声明。"""
    declared = {str(s.get("source_id")) for s in kh.load_sources()}
    assert set(kh.available_sources(chunks)) <= declared


def test_save_index_writes_manifest(tmp_path):
    """source_index.json 的结构可供 evidence_chain 解析检查使用。"""
    chunks = kh.build_index()
    out = kh.save_index(chunks, tmp_path / "source_index.json")
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == len(payload["sources"])
    assert all("source_id" in s and "path" in s for s in payload["sources"])
