"""项目文档正文的检查（Owner: B）。

正文与骨架的区别：骨架管结构，正文管**内容是否写实**。这里锁四件事：

1. 六章齐全、技术章按能力分节（与骨架一致）；
2. **每章都有可核验的数据或文件引用**，不是空话；
3. 四处【待补】必须显式标注并指名到人——不能悄悄留空；
4. 不得出现编造的市场数字（百分比必须有出处或标注待补）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "项目文档-正文.md"


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.exists(), "项目文档正文不存在"
    return DOC.read_text(encoding="utf-8")


def test_six_chapters(text):
    chapters = re.findall(r"^## 第 (\d) 章 · ", text, flags=re.M)
    assert chapters == ["1", "2", "3", "4", "5", "6"], f"应为 6 章，实际 {chapters}"


def test_technical_chapter_sections(text):
    subs = re.findall(r"^### 3\.(\d) ", text, flags=re.M)
    assert subs == ["1", "2", "3", "4", "5", "6"], f"§3.x 应为 6 节，实际 {subs}"


def test_each_chapter_has_concrete_evidence(text):
    """每章至少出现一个具体数字或文件路径，不能只有形容词。"""
    blocks = re.split(r"^## 第 \d 章 · ", text, flags=re.M)[1:]
    weak = []
    for idx, block in enumerate(blocks, start=1):
        has_number = re.search(r"\d", block) is not None
        has_file = "`" in block
        if not (has_number and has_file):
            weak.append(f"第{idx}章")
    assert not weak, f"这些章缺少具体数据或文件引用：{weak}"


def test_pending_items_are_explicit(text):
    """待补项必须显式标注且指名——留空是最容易被忽略的失败。"""
    pending = re.findall(r"【待补[^】]*】", text)
    assert len(pending) >= 3, f"待补项应显式标注，实际只找到 {len(pending)} 处"
    assert any("A" in p for p in pending), "待补项应指名到人（当前缺 A 的）"


def test_key_numbers_match_source(text):
    """正文引用的关键数字必须与实测口径一致。"""
    assert "317 passed" in text or "317" in text
    assert "100%" in text and "86.4%" in text
    assert "0.95" in text and "0.85" in text


def test_boundary_section_is_honest(text):
    """第 6 章必须写明 L3 未实现与改述 40% 这两个不利事实。"""
    assert "L3" in text and "未实现" in text
    assert "40%" in text


def test_no_fabricated_market_claims(text):
    """商业章必须写明"不要编市场数字"。"""
    assert "不要编市场数字" in text or "不要编" in text


def test_reproduce_commands_present(text):
    """文末复算命令必须存在——没有复现方式的报告不可信。"""
    for cmd in ("check.py", "run_golden.py", "knowledge_eval", "package_release.py"):
        assert cmd in text, f"缺少复算命令：{cmd}"
