"""测试报告的"防过期"检查（Owner: B）。

报告最怕的不是写错，是**写对之后代码又变了**。这里把报告里的关键数字
与实时计算绑定：数字一旦对不上，测试就红。

只锁两类：
    1. 检索命中率——报告里引用的百分比必须等于当前评测结果；
    2. 诚实声明——"L3 未实现"这类话必须还在（防止有人为了让材料好看删掉）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import knowledge_eval as ke  # noqa: E402

REPORT = ROOT / "docs" / "测试报告.md"


@pytest.fixture(scope="module")
def report_text() -> str:
    assert REPORT.exists(), "测试报告不存在"
    return REPORT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def live() -> ke.EvalReport:
    return ke.evaluate()


def test_hit_at_1_in_report_matches_live(report_text, live):
    expected = f"{live.hit_at_1:.2%}"
    assert expected in report_text, f"报告里的 hit@1 与实测 {expected} 不一致，报告已过期"


def test_hit_rate_in_report_matches_live(report_text, live):
    expected = f"{live.hit_rate:.0%}"
    assert expected in report_text, f"报告里的 hit@k 与实测 {expected} 不一致"


def test_mrr_in_report_matches_live(report_text, live):
    # 报告里写成三位小数（0.911 或 0.9106 都算对）
    assert f"{live.mrr:.3f}" in report_text or f"{live.mrr}" in report_text


def test_paraphrase_group_number_is_not_hidden(report_text, live):
    """改述组的真实命中率必须出现在报告里——这是最容易被省略的短板。"""
    para = [g for g in ke._groups(live) if "改述" in g[0]]
    assert para, "评测集里应含改述组"
    _, _, _, hit1, _ = para[0]
    assert f"{hit1:.0%}" in report_text, "报告没写出改述组的真实 hit@1"


def test_honest_disclosure_kept(report_text):
    """这些"不好看但必须留着"的话不能被删掉。"""
    for phrase in ("未实现", "L3", "不代表真实语料"):
        assert phrase in report_text, f"报告里的诚实声明被删了：{phrase}"
