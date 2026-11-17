"""路演 PPT 大纲的结构检查（Owner: B）。

计划里对 PPT 有三条硬约束，靠人眼核对容易漏：
    1. **12–15 页**；
    2. **契合度对照表必须在第 2 页**；
    3. **六项能力齐全**。

另外锁两条"材料纪律"：
    4. 每页都标了证据来源（没有证据的页不该上）；
    5. 边界页必须还在（L3 只观测不加权 / 改述 40% / Mock 的 L2 是启发式）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "路演PPT大纲.md"


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.exists(), "PPT 大纲不存在"
    return DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pages(text) -> list[int]:
    return [int(n) for n in re.findall(r"^## P(\d+) ·", text, flags=re.M)]


def test_page_count_within_range(pages):
    assert 12 <= len(pages) <= 15, f"计划要求 12–15 页，实际 {len(pages)} 页"


def test_page_numbers_are_sequential(pages):
    assert pages == list(range(1, len(pages) + 1)), f"页码应连续，实际 {pages}"


def test_mapping_table_is_on_page_two(text):
    """对照表必须在第 2 页——评审第一眼找的就是它。"""
    match = re.search(r"^## P2 · (.*)$", text, flags=re.M)
    assert match, "找不到 P2"
    assert "对照表" in match.group(1), f"P2 应是契合度对照表，实际是「{match.group(1)}」"


def test_all_six_capabilities_listed(text):
    for keyword in ("知识库", "Agent 团队", "工作流编排", "动态调度", "Self-Loop", "结果验证"):
        assert keyword in text, f"对照表缺少能力：{keyword}"


# 不要求标注证据的页：封面（无内容）、边界页（自述限制）、团队页（分工）
NO_EVIDENCE_NEEDED = {1: "封面", 13: "边界与已知限制", 14: "团队与分工"}


def test_each_content_page_declares_evidence(text, pages):
    """内容页都要有「证据」或「数据」标注，避免放没有依据的页。"""
    blocks = re.split(r"^## P\d+ · ", text, flags=re.M)[1:]
    weak = []
    for idx, block in enumerate(blocks, start=1):
        if idx in NO_EVIDENCE_NEEDED:
            continue
        if "**证据**" not in block and "**数据**" not in block:
            weak.append(f"P{idx}")
    assert not weak, f"这些页没有标注证据来源：{weak}"


def test_boundary_page_kept(text):
    """边界页是最好的防守，不能被删。

    L3 自 2026-11-14 已实现，所以"未实现"不再适用；改为要求写清它的
    **观测边界**（只观测/不加权），其余两条（改述 40%、启发式 L2）不变。
    """
    assert "边界与已知限制" in text
    for phrase in ("40%", "启发式"):
        assert phrase in text, f"边界页缺少诚实声明：{phrase}"
    assert ("只观测" in text) or ("不加权" in text), "边界页必须写清 L3 只观测/不加权"


def test_no_fabricated_screenshots_claim(text):
    """提醒：所有截图必须来自真实运行——这条写进制作要求里，不允许画示意图。"""
    assert "真实运行" in text
