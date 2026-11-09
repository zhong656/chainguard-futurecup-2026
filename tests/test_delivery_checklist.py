"""交付验收清单的有效性检查（Owner: B）。

清单过期和代码出错一样危险：命令改名了但清单没改，照着做会卡住。
所以这里校验三件事：
    1. 清单里出现的每个脚本**真的存在**；
    2. 6 条必跑命令齐全，且每条都写了期望输出；
    3. 红线项与"最后提交才算数"这类关键提醒还在。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "交付验收清单.md"

REQUIRED_SCRIPTS = (
    "check.py",
    "run_golden.py",
    "package_release.py",
    "collect_evidence.py",
    "verify_http.py",
    "count_intro.py",
)


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.exists(), "交付验收清单不存在"
    return DOC.read_text(encoding="utf-8")


def test_all_six_commands_listed(text):
    for script in REQUIRED_SCRIPTS:
        assert script in text, f"清单缺少命令：{script}"


def test_scripts_actually_exist():
    """清单里提到的脚本必须真实存在——防"改了名没改清单"。"""
    missing = [s for s in REQUIRED_SCRIPTS if not (ROOT / "scripts" / s).exists()]
    assert not missing, f"清单引用了不存在的脚本：{missing}"


def test_each_command_has_expected_output(text):
    """每条命令都要写"期望看到什么"，否则没法判断自己是否通过。"""
    rows = re.findall(r"^\| \d \| `python scripts/(\S+)` \| (.+?) \|", text, flags=re.M)
    assert len(rows) >= 6, f"应为 6 条命令表格行，实际 {len(rows)}"
    weak = [name for name, expectation in rows if len(expectation.strip()) < 4]
    assert not weak, f"这些命令没写期望输出：{weak}"


def test_red_lines_are_enumerated(text):
    """红线检查至少 7 条，且必须包含"公开仓库"与"Key"两类。"""
    boxes = text.count("- [ ]")
    assert boxes >= 7, f"红线检查项只有 {boxes} 条，应 ≥7"
    assert "public" in text or "private" in text
    assert "Key" in text


def test_final_submission_warning(text):
    """必须写明"最后提交的一份才算数"。"""
    assert "最后提交的一份才算数" in text


def test_baseline_is_main_not_branch(text):
    """必须提醒"分支上做完不等于 main 上有"。"""
    assert "分支内结论不算" in text or "分支上做完不等于" in text


def test_materials_map_to_sources(text):
    """六项材料都要写清从哪来。"""
    for item in ("作品简介", "项目文档", "演示视频", "源码与可运行包", "示例输出包", "测试报告"):
        assert item in text, f"材料映射缺项：{item}"
