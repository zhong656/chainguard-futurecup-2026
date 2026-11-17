"""作品简介的提交口径检查（Owner: B）。

两道关：
    1. **字数**：A 版必须 ≤300 字（提交表硬限），且留有余量；
    2. **覆盖**：六项能力的关键词都要出现 —— "概括全" 是这次的要求，
       少一块就是漏项，靠人眼对容易漏。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import count_intro  # noqa: E402

DOC = ROOT / "docs" / "作品简介.md"
LIMIT = 300
SAFETY = 295  # 给不同字数统计口径留余量


@pytest.fixture(scope="module")
def text() -> str:
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def version_a(text) -> str:
    return count_intro.extract_a(text)


def test_intro_exists_and_parses(text):
    assert "## A 版" in text, "作品简介缺少 A 版（投稿版）"
    assert "## B 版" in text, "作品简介缺少 B 版（展开版）"


def test_version_a_within_limit(version_a):
    n = count_intro.count_chars(version_a)
    assert n <= LIMIT, f"A 版 {n} 字，超过 {LIMIT} 字上限"
    assert n <= SAFETY, f"A 版 {n} 字，超过留有余量的 {SAFETY} 字（不同统计口径可能判超）"


def test_version_a_covers_all_six_capabilities(version_a):
    """六项能力各至少一个关键词，缺一项就是漏项。"""
    keywords = {
        "1 知识库": ["语料", "检索"],
        "2 Agent 团队": ["角色", "YAML"],
        "3 工作流编排": ["DAG", "节点"],
        "4 动态调度": ["调度", "降级"],
        "5 Self-Loop": ["Self-Loop", "重跑"],
        "6 验证与反馈": ["验证", "反馈"],
    }
    missing = [name for name, words in keywords.items() if not any(w in version_a for w in words)]
    assert not missing, f"A 版漏了这些能力：{missing}"


def test_version_a_claims_verifiable_delivery(version_a):
    """本项目的差异点是"可核验"，简介里必须落到具体机制上。"""
    assert "manifest" in version_a
    assert "sha256" in version_a


def test_no_overclaim_in_intro(text):
    """不许出现"三层验证全部实现"这类经不起追问的说法。"""
    banned = ["三层验证全部", "全部实现", "100% 准确", "完全准确"]
    for phrase in banned:
        assert phrase not in text, f"简介里出现过度声明：{phrase}"
    assert "L3" in text, "B 版必须写明 L3 的边界（只观测/不加权）"


def test_version_a_has_no_l3_claim(version_a):
    """A 版说"分两层"是准确的；如果说"三层"就与实现不符。"""
    assert "两层" in version_a
    assert "三层" not in version_a
