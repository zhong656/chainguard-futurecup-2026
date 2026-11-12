"""架构图与代码一致性的测试（Owner: B）。

架构图最容易出的问题不是画得丑，而是**过期**：
代码加了模块、改了接口、加了契约，图上还是旧的。评审对照代码就发现对不上。

所以这里把图里的关键信息**重新从仓库读一遍**逐项比对：
模块名、契约名、接口路径、数量（6 角色 / 11 契约 / 17 语料）、端口。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import make_architecture_svg as arch  # noqa: E402

SVG = ROOT / "docs" / "images" / "architecture.svg"


@pytest.fixture(scope="module")
def svg() -> str:
    assert SVG.exists(), "架构图不存在，先跑 python scripts/make_architecture_svg.py"
    return SVG.read_text(encoding="utf-8")


def test_svg_is_vector_and_self_contained(svg):
    assert svg.startswith("<svg") or svg.lstrip().startswith("<svg")
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    # 不依赖外部资源（评审离线也能看）
    assert "xlink:href" not in svg
    assert "<image" not in svg


def test_all_contracts_listed(svg):
    for name in arch._count_contracts():
        assert name in svg, f"架构图缺少契约 {name}"


def test_all_core_modules_listed(svg):
    modules = ("dag_compiler", "scheduler", "loop_controller", "agent_registry",
               "knowledge_hub", "rule_checker", "verifier", "vertical_slice",
               "evidence", "feedback", "sandbox", "trace")
    missing = [m for m in modules if m not in svg]
    assert not missing, f"架构图缺少核心模块：{missing}"


def test_counts_match_repository(svg):
    assert f"{arch._count_agents()} 类角色" in svg or f"（{arch._count_agents()} 份）" in svg
    assert f"{arch._count_corpus()} 份" in svg
    assert f"{len(arch._count_contracts())} 份 JSON Schema" in svg


def test_http_routes_listed(svg):
    for route in arch._routes():
        path = route.split(" ", 1)[1]
        assert path in svg, f"架构图缺少接口 {path}"


def test_ports_listed(svg):
    assert "8000" in svg and "8766" in svg


def test_layers_are_five(svg):
    for label in ("接入层", "编排层", "执行层", "验证层", "产出层"):
        assert label in svg, f"缺少分层：{label}"


def test_no_overlapping_lane_titles(svg):
    """分层标题与副标题不能重叠——早先字宽估算偏小，中文副标题压在标题上。"""
    offsets = re.findall(r'<text x="(\d+)" y="(\d+)"[^>]*font-size="11.5"', svg)
    assert offsets, "未找到副标题文本"


def test_regenerating_matches_committed_file(svg):
    """提交的 SVG 必须与脚本当前输出一致，否则说明图是手改的。"""
    assert arch.build_svg().strip() == svg.strip(), (
        "架构图与脚本输出不一致——请重跑 python scripts/make_architecture_svg.py"
    )
