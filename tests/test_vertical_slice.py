"""纵切验收：检查真实模块连通、回退、文件哈希和失败路径。"""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts._schema import validator
from src.llm_adapter import MockLLMAdapter, parse_draft
from src.trace import read_trace
from src.vertical_slice import VerticalSliceError, run_vertical_slice


def test_mock_adapter_emits_valid_contract_and_only_retrieved_ids():
    retrieval = {
        "query": "机器视觉质检", "mode": "hybrid", "items": [
            {"source_id": "mv:doc001", "score": 1.0, "snippet": "光源稳定性影响检测。"},
        ],
    }
    response = MockLLMAdapter().generate_draft("机器视觉质检", retrieval, run_id="test-run")
    validator("llm_response.schema.json").validate(response)
    draft = parse_draft(response)
    assert len(draft["sections"]) == 6
    assert all(section["citations"] == ["mv:doc001"] for section in draft["sections"])
    assert response["usage"] == {"tokens_in": 0, "tokens_out": 0}


def test_vertical_slice_revises_once_and_exports_verified_files(tmp_path):
    request = "用机器视觉升级精密零件产线质检"
    result = run_vertical_slice(request, output=tmp_path, run_id="test-vertical")
    artifact = result["artifact"]
    validator("delivery_artifact.schema.json").validate(artifact)
    assert result["round"] == result["scorecard"]["round"] == 1
    assert result["scorecard"]["verdict"] == "pass"
    assert set(artifact["evidence_chain"]) <= {i["source_id"] for i in result["retrieval"]["items"]}
    assert len(artifact["evidence_chain"]) > 0
    events = read_trace(tmp_path / "trace.jsonl")
    starts = [item["node_id"] for item in events if item["kind"] == "start"]
    assert starts.count("retrieve") == 1
    assert starts.count("write") == starts.count("verify") == starts.count("gate") == 2
    assert {"plan", "retrieve", "fanout", "analyze", "outline", "write", "verify", "gate", "revise", "review", "snap"} <= set(starts)
    assert any(item["kind"] == "revise" and "write" in item["reason"] for item in events)
    assert request not in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "delivery_artifact.json").read_text(encoding="utf-8")) == artifact
    for item in artifact["manifest"]["files"]:
        payload = (tmp_path / item["path"]).read_bytes()
        assert len(payload) == item["bytes"]
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]


def test_vertical_slice_without_injected_gap_passes_without_revision(tmp_path):
    result = run_vertical_slice("产线质检", output=tmp_path, inject_initial_gap=False)
    assert result["round"] == 0
    assert result["scorecard"]["verdict"] == "pass"


def test_vertical_slice_rejects_missing_source_manifest(tmp_path):
    with pytest.raises(VerticalSliceError, match="语料清单不存在"):
        run_vertical_slice("产线质检", sources_path=tmp_path / "sources.yaml")


def test_vertical_slice_rejects_unreadable_declared_corpus(tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(
        "sources:\n  - source_id: mv:missing\n    path: corpus/missing.md\n",
        encoding="utf-8",
    )
    with pytest.raises(VerticalSliceError, match="缺少可读取片段"):
        run_vertical_slice("产线质检", sources_path=sources, corpus_dir=tmp_path / "corpus")
