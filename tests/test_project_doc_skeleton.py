"""项目文档骨架的结构检查（Owner: B）。

计划里对材料 #2 的要求：
    1. **契合度对照表在第 2 页**；
    2. **每项能力附「实现 + 截图 + 数据」**；
    3. 不得出现校名、导师、个人身份信息。

本测试只校验骨架，不校验最终排版（排版要等官方模板）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "项目文档-骨架.md"


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.exists(), "项目文档骨架不存在"
    return DOC.read_text(encoding="utf-8")


def test_six_chapters_present(text):
    chapters = re.findall(r"^## 第 (\d) 章 · ", text, flags=re.M)
    assert chapters == ["1", "2", "3", "4", "5", "6"], f"应为 6 章，实际 {chapters}"


def test_six_capabilities_covered(text):
    for keyword in ("知识库", "Agent 团队", "工作流编排", "动态调度", "Self-Loop", "结果验证"):
        assert keyword in text, f"缺少能力：{keyword}"


def test_six_subsections_in_chapter3(text):
    """技术实现章必须逐能力分节，不能揉成一大段。"""
    subs = re.findall(r"^### §3\.(\d)", text, flags=re.M)
    assert subs == ["1", "2", "3", "4", "5", "6"], f"§3.x 应为 6 节，实际 {subs}"


def test_mapping_table_is_pre_page_two(text):
    """对照表必须标在第 2 页——这是评审第一眼找的东西。"""
    assert "第 2 页" in text
    assert "契合度对照表" in text


def test_each_chapter_lists_evidence(text):
    """每章都要写清用哪个数据/截图，否则后期没人知道该补什么。"""
    blocks = re.split(r"^## 第 \d 章 · ", text, flags=re.M)[1:]
    assert len(blocks) == 6
    for idx, block in enumerate(blocks, start=1):
        assert ("用哪张证据" in block) or ("证据：" in block), f"第 {idx} 章没写证据来源"


def test_missing_items_are_tracked(text):
    """骨架里标了 ⏳ 的东西必须有汇总，否则会漏。"""
    assert "待补事项" in text
    assert text.count("⏳") >= 5, "应至少标出 5 处待补项"


def test_no_personal_identity_leak(text):
    """提交材料不得出现校名、导师、个人身份信息。

    注意：**禁止性说明本身必须提到这些词**（"不写校名、导师姓名"），
    所以逐行判断，跳过明确在"禁止/要求去掉"的句子，否则测试会误报。
    """
    banned = ["大学", "学院", "指导老师", "导师", "学号"]
    guard = ("不写", "不得", "去掉", "禁止", "不包括")
    offenders = []
    for line in text.splitlines():
        if any(marker in line for marker in guard):
            continue
        for word in banned:
            if word in line:
                offenders.append(f"{word} → {line.strip()[:60]}")
    assert not offenders, "骨架里出现了不应提交的信息：" + "；".join(offenders)


def test_no_fabricated_market_claims(text):
    """商业模式章必须写明"不许编市场数字"。"""
    assert "不要编市场数字" in text or "不许编市场数字" in text
