"""方案书的合规与质量检查（Owner: B）。

对着**官方初赛要求**逐条验，而不是对着我们自己的想象验：
    1. 字数 ≥5000（官方原文：字数不少于 5000 字）；
    2. 八个必含部分一个不少（官方 P25 逐条列出）；
    3. 涉及的截图文件真实存在（不能引用不存在的图）；
    4. 不许出现"已实现 L3""高并发"这类与事实冲突的表述。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "方案书-正文.md"

# 官方 P25 要求的八个部分（关键词 -> 说明）
REQUIRED_PARTS = {
    "选题背景": "选题背景与场景需求分析",
    "架构设计": "平台总体架构设计与技术选型说明",
    "Agent 角色定义": "Agent 角色定义、工作流设计与编排逻辑",
    "调度算法": "调度算法与自我循环机制说明",
    "结果验证策略": "结果验证策略与反馈优化逻辑",
    "核心代码模块说明": "核心代码模块说明与系统截图",
    "测试用例": "测试用例、运行效果与性能评估",
    "人工智能使用说明": "人工智能使用说明（LLM/RAG/MCP）",
}


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.exists(), "方案书正文不存在"
    return DOC.read_text(encoding="utf-8")


def test_word_count_meets_official_minimum(text):
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    han = len(re.findall(r"[\u4e00-\u9fff]", body))
    assert han >= 5000, f"汉字 {han} 少于官方要求的 5000 字"


def test_all_eight_official_parts_present(text):
    missing = [desc for key, desc in REQUIRED_PARTS.items() if key not in text]
    assert not missing, f"缺少官方要求的章节：{missing}"


def test_screenshot_links_resolve(text):
    """引用的截图必须真实存在——文档里挂空图是最常见的低级错误。"""
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    assert refs, "方案书应包含系统截图"
    missing = [r for r in refs if not (DOC.parent / r).exists()]
    assert not missing, f"引用的截图不存在：{missing}"


def test_honest_limitations_present(text):
    """必须写明 L3 的实现边界、改述 hit@1 40%、并发压测未做。

    L3 自 2026-11-14 起已实现，但**它只观测不加权**——这句边界同样必须写出来，
    否则读者会以为它参与总分。
    """
    assert "L3" in text
    assert ("只观测" in text) or ("不加权" in text), "L3 必须写明只观测/不加权"
    assert "未实现" in text, "仍有未实现的部分（HTTP+SSE / resources / sampling）"
    assert "40%" in text
    assert "并发" in text and "未做" in text


def test_no_false_claims(text):
    """禁止与事实冲突的表述。"""
    forbidden = ("已实现 L3", "已接入 MCP", "高并发", "压测通过")
    hits = [w for w in forbidden if w in text]
    assert not hits, f"出现了与事实冲突的表述：{hits}"


def test_key_numbers_present(text):
    """核心数据必须在正文里，便于评审核对。"""
    for token in ("11 份", "17 份", "0.85", "0.75"):
        assert token in text, f"缺少关键数据：{token}"


def test_personal_info_not_in_repo(text):
    """仓库要转公开：方案书正文不得写学校/指导教师/学号等信息。"""
    for token in ("岭南师范学院", "石艳", "骆俊", "龙在飞"):
        assert token not in text, f"方案书正文出现了个人信息：{token}"

def test_scorecard_dimensions_match_config(text):
    """方案书里的评分维度与权重必须与 configs/verifier.yaml 完全一致。

    这条是因为真实踩过：初稿把维度写成 evidence/completeness/readability，
    而代码里是 citation/consistency/coverage/logic/format——文档与实现对不上，
    评审一跑就露馅。
    """
    import yaml

    cfg = yaml.safe_load((ROOT / "configs" / "verifier.yaml").read_text(encoding="utf-8"))
    weights = cfg["scorecard"]["weights"]
    for name, weight in weights.items():
        assert name in text, f"方案书缺少真实维度 {name}"
        assert f"{weight:.2f}" in text, f"方案书缺少 {name} 的真实权重 {weight}"


def test_no_undated_test_counts(text):
    """凡写"多少 passed"，必须带日期或提交号——防止把会变的数字写成恒真断言。

    这是 A 在 #82/#84 review 里指出的同一类问题：测试锁死运行测试数，
    过时值就变成了"通过"。
    """
    for line in text.splitlines():
        if "passed" in line:
            assert ("2026-" in line) or ("基线" in line), (
                f"这行写了 passed 却没有日期/基线：{line.strip()[:60]}"
            )
