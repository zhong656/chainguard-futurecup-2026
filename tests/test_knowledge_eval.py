"""检索评测的测试（Owner: B）。

评测工具本身也要被评测 —— 否则"命中率 100%"可能只是统计写错了。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import knowledge_eval as ke  # noqa: E402


@pytest.fixture(scope="module")
def report():
    return ke.evaluate()


def test_report_covers_all_queries(report):
    data = ke.load_queries()
    assert report.total == len(data["queries"])
    assert report.top_k >= 1


def test_metrics_are_in_range(report):
    assert 0.0 <= report.hit_rate <= 1.0
    assert 0.0 <= report.hit_at_1 <= 1.0
    assert 0.0 <= report.mrr <= 1.0
    # hit@1 不可能比 hit@k 高
    assert report.hit_at_1 <= report.hit_rate


def test_paraphrase_group_is_separated(report):
    """改述组必须单独统计 —— 只报总分容易高估。"""
    groups = ke._groups(report)
    names = [g[0] for g in groups]
    assert any("改述" in n for n in names)
    assert any("原文词" in n for n in names)
    total = sum(g[1] for g in groups)
    assert total == report.total


def test_unknown_expected_id_raises(tmp_path):
    """期望的 source_id 不在索引里时，必须报错而不是静默算作未命中。"""
    bad = tmp_path / "q.yaml"
    bad.write_text(
        "version: 1\ntop_k: 5\nqueries:\n  - id: x1\n    query: 机器视觉\n    expected: [mv:does-not-exist]\n",
        encoding="utf-8",
    )
    with pytest.raises(ke.EvalError):
        ke.evaluate(queries_path=bad)


def test_empty_query_raises(tmp_path):
    bad = tmp_path / "q.yaml"
    bad.write_text("version: 1\nqueries:\n  - id: x1\n    query: '   '\n    expected: [mv:doc001]\n", encoding="utf-8")
    with pytest.raises(ke.EvalError):
        ke.evaluate(queries_path=bad)


def test_markdown_contains_headline_numbers(report):
    md = ke.render_markdown(report)
    assert "hit@8" in md or f"hit@{report.top_k}" in md
    assert "MRR" in md
    assert "| 组 |" in md
