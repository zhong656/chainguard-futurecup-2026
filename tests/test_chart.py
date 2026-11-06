"""图表工具的边界测试（Owner: B）。

重点验三件"评审会在意"的事：
    1. 输出是合法 XML（浏览器/PDF 能打开）
    2. **同一输入逐字节可复现**（manifest 的 sha256 才有意义）
    3. 非法输入拒绝，而不是画出一张错图
"""

from __future__ import annotations

import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tools import chart  # noqa: E402


def test_bar_chart_is_valid_svg(tmp_path):
    out = chart.bar_chart(["规划", "分析", "写作"], [0.9, 0.75, 0.85], tmp_path / "bar.svg", title="维度得分")
    text = out.read_text(encoding="utf-8")
    root = ET.fromstring(text)  # 解析失败就说明不是合法 XML
    assert root.tag.endswith("svg")
    assert "维度得分" in text


def test_same_input_same_bytes(tmp_path):
    """逐字节可复现：manifest 里记录 sha256 的前提。"""
    a = chart.bar_chart(["甲", "乙"], [1.0, 2.0], tmp_path / "a.svg", title="T")
    b = chart.bar_chart(["甲", "乙"], [1.0, 2.0], tmp_path / "b.svg", title="T")
    assert hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(b.read_bytes()).hexdigest()


def test_no_timestamp_or_random_id(tmp_path):
    """SVG 里不能带时间戳/随机 id，否则每次出图哈希都变。"""
    out = chart.bar_chart(["甲"], [1.0], tmp_path / "x.svg")
    text = out.read_text(encoding="utf-8")
    for banned in ("2026-", "Generated", "uuid", "time"):
        assert banned not in text, f"输出里不应出现 {banned}"


def test_labels_are_escaped(tmp_path):
    """`<` `&` 出现在标签里不能破坏 XML。"""
    out = chart.bar_chart(["成本 <10 万", "A&B"], [1.0, 2.0], tmp_path / "e.svg")
    ET.fromstring(out.read_text(encoding="utf-8"))
    assert "&lt;" in out.read_text(encoding="utf-8")


def test_line_chart_with_threshold(tmp_path):
    """Self-Loop 收敛曲线：能标出阈值线。"""
    out = chart.line_chart(["R0", "R1", "R2"], [0.78, 0.83, 0.9], tmp_path / "line.svg", threshold=0.85, title="收敛")
    text = out.read_text(encoding="utf-8")
    ET.fromstring(text)
    assert "阈值 0.85" in text


def test_single_point_line_chart(tmp_path):
    """只有一个点时不能除零。"""
    out = chart.line_chart(["R0"], [0.5], tmp_path / "one.svg")
    ET.fromstring(out.read_text(encoding="utf-8"))


def test_rejects_mismatched_lengths(tmp_path):
    with pytest.raises(chart.ChartError):
        chart.bar_chart(["a", "b"], [1.0], tmp_path / "x.svg")


def test_rejects_non_finite(tmp_path):
    for bad in (float("nan"), float("inf")):
        with pytest.raises(chart.ChartError):
            chart.bar_chart(["a"], [bad], tmp_path / "x.svg")


def test_rejects_empty_labels(tmp_path):
    with pytest.raises(chart.ChartError):
        chart.bar_chart(["a", " "], [1.0, 2.0], tmp_path / "x.svg")


def test_rejects_non_svg_output(tmp_path):
    with pytest.raises(chart.ChartError):
        chart.bar_chart(["a"], [1.0], tmp_path / "x.png")


def test_all_zero_values_do_not_crash(tmp_path):
    out = chart.bar_chart(["a", "b"], [0.0, 0.0], tmp_path / "z.svg")
    ET.fromstring(out.read_text(encoding="utf-8"))


def test_negative_bar_value_is_rejected_instead_of_drawing_negative_height(tmp_path):
    with pytest.raises(chart.ChartError, match="负值"):
        chart.bar_chart(["收益", "亏损"], [1.0, -0.5], tmp_path / "bad.svg")
    assert not (tmp_path / "bad.svg").exists()


def test_threshold_remains_visible_when_every_round_is_below_it(tmp_path):
    out = chart.line_chart(["R0", "R1"], [0.4, 0.5], tmp_path / "below.svg", threshold=0.85)
    text = out.read_text(encoding="utf-8")
    ET.fromstring(text)
    assert "阈值 0.85" in text


def test_nonfinite_threshold_is_rejected(tmp_path):
    with pytest.raises(chart.ChartError, match="threshold"):
        chart.line_chart(["R0"], [0.5], tmp_path / "bad.svg", threshold=float("nan"))


def test_real_use_case_roi_comparison(tmp_path):
    """真实场景：三个方案的一次性投入对比。"""
    out = chart.bar_chart(
        ["方案A", "方案B", "方案C"], [12.0, 9.5, 15.2],
        tmp_path / "roi.svg", title="单工位改造成本（万元）", unit=" 万",
    )
    text = out.read_text(encoding="utf-8")
    ET.fromstring(text)
    assert "12.00 万" in text
