"""HANDOFF 的数字必须现场查，不得写死（Owner: B）。

A 在 #85 授权把基线改成动态查询，起因是：写死的 `178 文件 / 303 passed`
每合并一次就过时，而过时数字看起来仍然"权威"。

这里锁住形式：HANDOFF 的 main / 文件数 / 测试 / 打开 PR 四行里，
**不得出现裸的数字结论**（命令与字段名可以有，但要明显是命令）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "HANDOFF.md"


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.exists()
    return DOC.read_text(encoding="utf-8")


def _row(text: str, key: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"| {key} "):
            return line
    return ""


def test_main_row_has_command_not_hash(text):
    row = _row(text, "`main`")
    assert row, "HANDOFF 缺少 main 行"
    assert "git rev-parse" in row, "main 行应给命令，而不是固定哈希"
    assert not re.search(r"`[0-9a-f]{7}`", row), "main 行仍写死了提交哈希"


def test_file_and_test_row_has_commands(text):
    row = _row(text, "文件数 / 测试")
    assert row, "缺少文件数/测试行"
    assert "git ls-tree" in row and "check.py" in row
    assert not re.search(r"\*\*\d+ 个文件\*\*", row), "仍写死了文件数"
    assert not re.search(r"\*\*\d+ (?:个)?测试", row), "仍写死了测试数"


def test_open_pr_row_has_command(text):
    row = _row(text, "打开中的 PR")
    assert row, "缺少打开中的 PR 行"
    assert "gh pr list" in row, "应给命令"
    assert not re.search(r"\*\*\d+\*\*", row), "仍写死了 PR 数量"
