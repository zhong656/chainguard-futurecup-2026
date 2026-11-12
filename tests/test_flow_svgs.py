"""流程类矢量图与真实数据的一致性测试（Owner: B）。

时序图最容易造假的点：**用编好的时间画一条好看的流程**。
所以这里直接读 `trace.jsonl`，逐项核对图里出现的节点、轮次、事件数与实测一致。

证据链图同理：图上写的文件、字段、检查项必须真实存在。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_flow_svgs as flow  # noqa: E402

SEQ = ROOT / "docs" / "images" / "sequence.svg"
EVID = ROOT / "docs" / "images" / "evidence-flow.svg"
TRACE = ROOT / "outputs" / "_viz" / "trace.jsonl"


@pytest.fixture(scope="module")
def seq() -> str:
    assert SEQ.exists(), "时序图不存在，先跑 python scripts/make_flow_svgs.py"
    return SEQ.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def evid() -> str:
    assert EVID.exists(), "证据链图不存在"
    return EVID.read_text(encoding="utf-8")


def test_svgs_are_self_contained(seq, evid):
    for svg in (seq, evid):
        assert 'xmlns="http://www.w3.org/2000/svg"' in svg
        assert "<image" not in svg, "不应嵌入位图"


def test_sequence_uses_real_nodes(seq):
    """图里的节点必须来自真实 trace，不能只画好看的几个。"""
    if not TRACE.exists():
        pytest.skip("没有 trace 产物（outputs/_viz 未生成）")
    events = [json.loads(l) for l in TRACE.read_text(encoding="utf-8").strip().splitlines() if l.strip()]
    nodes = {e["node_id"] for e in events}
    for node in nodes:
        assert f">{node}<" in seq or node in seq, f"时序图缺少真实节点 {node}"


def test_sequence_reports_real_event_count(seq):
    if not TRACE.exists():
        pytest.skip("没有 trace 产物")
    events = [json.loads(l) for l in TRACE.read_text(encoding="utf-8").strip().splitlines() if l.strip()]
    assert f"{len(events)} 个事件" in seq, "事件数标注与 trace 不一致"


def test_sequence_marks_both_rounds(seq):
    assert "第 0 轮" in seq and "第 1 轮" in seq
    assert "fail" in seq and "pass" in seq


def test_evidence_flow_mentions_real_files(evid):
    for token in ("knowledge_hub.py", "evidence.py", "evidence_refs.json",
                  "rule_checker.py", "delivery_artifact.json", "manifest"):
        assert token in evid, f"证据链图缺少 {token}"


def test_evidence_flow_lists_all_five_rules(evid):
    for code in ("SCHEMA_INVALID", "CITATION_MISSING", "CITATION_UNKNOWN",
                 "NUMERIC_MISMATCH", "MISSING_SECTION"):
        assert code in evid, f"证据链图缺少规则 {code}"


def test_evidence_flow_lists_all_nine_deliverables(evid):
    for f in ("solution.md", "evidence_chain.json", "scorecard.json", "rounds.json",
              "trace.jsonl", "scorecard.svg", "convergence.svg", "delivery_artifact.json"):
        assert f in evid, f"证据链图缺少交付物 {f}"


def test_page_null_caliber_is_stated(evid):
    """页码口径必须写在图上——否则读者会以为 PDF 页码已验证。"""
    assert "page" in evid and "null" in evid


def test_regenerating_matches_committed_files(seq, evid):
    """提交的图必须与脚本输出一致（防手改、防过期）。"""
    if not TRACE.exists():
        pytest.skip("没有 trace 产物")
    assert flow.build_sequence(TRACE).strip() == seq.strip(), "时序图与脚本输出不一致"
    assert flow.build_evidence_flow().strip() == evid.strip(), "证据链图与脚本输出不一致"
