"""纵切验收：检查真实模块连通、回退、文件哈希和失败路径。"""

from __future__ import annotations

import hashlib
import json

import pytest
import yaml

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


def test_vertical_slice_uses_l2_when_enabled(tmp_path, monkeypatch):
    import src.vertical_slice as vertical_slice

    called = []
    original = vertical_slice.default_verifier

    def wrapped():
        called.append(True)
        return original()

    monkeypatch.setattr(vertical_slice, "default_verifier", wrapped)
    result = run_vertical_slice("产线质检", output=tmp_path, inject_initial_gap=False)
    assert called
    assert result["scorecard"]["metrics"]["logic"] == 1.0


def test_vertical_slice_uses_l1_when_l2_disabled(tmp_path, monkeypatch):
    import src.vertical_slice as vertical_slice

    config = yaml.safe_load(vertical_slice.VERIFIER_CONFIG.read_text(encoding="utf-8"))
    config["layers"]["llm_judge"] = False
    config_path = tmp_path / "verifier.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(vertical_slice, "VERIFIER_CONFIG", config_path)
    monkeypatch.setattr(
        vertical_slice, "default_verifier",
        lambda: pytest.fail("L2 不应执行"),
    )
    result = run_vertical_slice("产线质检", output=tmp_path, inject_initial_gap=False)
    assert result["scorecard"]["verdict"] == "pass"


@pytest.mark.parametrize("key,value", [("rules", False), ("cross_check", True)])
def test_vertical_slice_rejects_unsupported_layers(tmp_path, monkeypatch, key, value):
    import src.vertical_slice as vertical_slice

    config = yaml.safe_load(vertical_slice.VERIFIER_CONFIG.read_text(encoding="utf-8"))
    config["layers"][key] = value
    config_path = tmp_path / "verifier.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(vertical_slice, "VERIFIER_CONFIG", config_path)
    with pytest.raises(ValueError, match="必须开启|尚未实现"):
        run_vertical_slice("产线质检")


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
