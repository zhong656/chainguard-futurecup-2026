"""图表渲染 —— 纯 SVG，零依赖（Owner: B）。

为什么不用 matplotlib
--------------------
1. **可复现**：`delivery_artifact.manifest.files[].sha256` 要求同一输入产出同一份字节。
   matplotlib 会写入版本号、时间戳、字体缓存路径，同一份数据两次出图哈希不同，
   manifest 就失去了"可核对"的意义。SVG 手写可以做到**逐字节确定**。
2. **零依赖**：评审只装 `pyyaml/jsonschema/pytest` 也能跑，不会因为缺字体或后端崩图。
3. **可 diff**：文本格式，`git diff` 能看出改了什么，二进制 PNG 不能。
4. **可缩放**：矢量图放进白皮书/PPT 不糊。

因此本模块只生成 SVG 字符串，不引入任何第三方库。
"""

from __future__ import annotations

import math
from pathlib import Path
from xml.sax.saxutils import escape

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 360
PAD_LEFT = 64
PAD_RIGHT = 24
PAD_TOP = 48
PAD_BOTTOM = 56

PALETTE = ("#2f6feb", "#e8590c", "#0ca678", "#845ef7", "#f08c00", "#c2255c")


class ChartError(ValueError):
    """输入不合法，拒绝出图。"""


def _check(labels: list[str], values: list[float]) -> None:
    if not labels or not values:
        raise ChartError("labels 与 values 不能为空")
    if len(labels) != len(values):
        raise ChartError(f"labels({len(labels)}) 与 values({len(values)}) 长度必须一致")
    for v in values:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise ChartError(f"数值必须是数字，收到 {type(v).__name__}")
        if not math.isfinite(float(v)):
            raise ChartError(f"数值必须有限，收到 {v}")
    if any(not str(label).strip() for label in labels):
        raise ChartError("label 不能为空字符串")


def _svg(width: int, height: int, body: list[str]) -> str:
    """固定画布骨架。不写生成时间、不写随机 id，保证逐字节可复现。"""
    if width <= PAD_LEFT + PAD_RIGHT or height <= PAD_TOP + PAD_BOTTOM:
        raise ChartError(f"画布太小：{width}x{height}")
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img">'
    )
    style = (
        "<style>"
        "text{font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans SC',sans-serif;}"
        ".axis{stroke:#adb5bd;stroke-width:1}"
        ".grid{stroke:#e9ecef;stroke-width:1}"
        ".label{fill:#495057;font-size:12px}"
        ".value{fill:#212529;font-size:11px}"
        ".title{fill:#212529;font-size:15px;font-weight:600}"
        "</style>"
    )
    return "\n".join([head, style, *body, "</svg>"]) + "\n"


def _title(text: str, width: int) -> list[str]:
    if not text:
        return []
    return [f'<text class="title" x="{width // 2}" y="28" text-anchor="middle">{escape(text)}</text>']


def _empty_guard(values: list[float]) -> float:
    peak = max(values)
    return peak if peak > 0 else 1.0


def bar_chart(
    labels: list[str],
    values: list[float],
    out: Path,
    *,
    title: str = "",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    unit: str = "",
) -> Path:
    """竖向柱状图。适合成本对比、各维度得分。"""
    _check(labels, values)
    if any(v < 0 for v in values):
        raise ChartError("柱状图不支持负值，不能生成负高度柱")
    peak = _empty_guard([float(v) for v in values])
    plot_w = width - PAD_LEFT - PAD_RIGHT
    plot_h = height - PAD_TOP - PAD_BOTTOM
    slot = plot_w / len(values)
    bar_w = slot * 0.55

    body = _title(title, width)
    # 网格 + 刻度
    for i in range(5):
        ratio = i / 4
        y = PAD_TOP + plot_h * (1 - ratio)
        body.append(f'<line class="grid" x1="{PAD_LEFT}" y1="{y:.1f}" x2="{width - PAD_RIGHT}" y2="{y:.1f}"/>')
        body.append(
            f'<text class="label" x="{PAD_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{peak * ratio:.2f}</text>"
        )
    # 坐标轴
    body.append(f'<line class="axis" x1="{PAD_LEFT}" y1="{PAD_TOP}" x2="{PAD_LEFT}" y2="{PAD_TOP + plot_h}"/>')
    body.append(
        f'<line class="axis" x1="{PAD_LEFT}" y1="{PAD_TOP + plot_h}" '
        f'x2="{width - PAD_RIGHT}" y2="{PAD_TOP + plot_h}"/>'
    )
    # 柱与数值
    for idx, (label, value) in enumerate(zip(labels, values)):
        v = float(value)
        h = plot_h * (v / peak) if peak else 0.0
        x = PAD_LEFT + slot * idx + (slot - bar_w) / 2
        y = PAD_TOP + plot_h - h
        color = PALETTE[idx % len(PALETTE)]
        body.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" '
            f'fill="{color}" rx="2"/>'
        )
        body.append(
            f'<text class="value" x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle">'
            f"{v:.2f}{escape(unit)}</text>"
        )
        body.append(
            f'<text class="label" x="{x + bar_w / 2:.1f}" y="{PAD_TOP + plot_h + 18:.1f}" '
            f'text-anchor="middle">{escape(str(label))}</text>'
        )
    return _write(out, _svg(width, height, body))


def line_chart(
    labels: list[str],
    values: list[float],
    out: Path,
    *,
    title: str = "",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    threshold: float | None = None,
) -> Path:
    """折线图。适合 Self-Loop 的分数收敛曲线（每轮一个点）。"""
    _check(labels, values)
    if threshold is not None and (
        isinstance(threshold, bool) or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
    ):
        raise ChartError("threshold 必须是有限数值")
    axis_values = [0.0, *[float(v) for v in values]]
    if threshold is not None:
        axis_values.append(float(threshold))
    low = min(axis_values)
    high = max(axis_values) or 1.0
    span = (high - low) or 1.0
    plot_w = width - PAD_LEFT - PAD_RIGHT
    plot_h = height - PAD_TOP - PAD_BOTTOM

    def x_of(i: int) -> float:
        if len(values) == 1:
            return PAD_LEFT + plot_w / 2
        return PAD_LEFT + plot_w * i / (len(values) - 1)

    def y_of(v: float) -> float:
        return PAD_TOP + plot_h * (1 - (float(v) - low) / span)

    body = _title(title, width)
    for i in range(5):
        ratio = i / 4
        y = PAD_TOP + plot_h * (1 - ratio)
        body.append(f'<line class="grid" x1="{PAD_LEFT}" y1="{y:.1f}" x2="{width - PAD_RIGHT}" y2="{y:.1f}"/>')
        body.append(
            f'<text class="label" x="{PAD_LEFT - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{low + span * ratio:.2f}</text>"
        )
    body.append(f'<line class="axis" x1="{PAD_LEFT}" y1="{PAD_TOP}" x2="{PAD_LEFT}" y2="{PAD_TOP + plot_h}"/>')
    body.append(
        f'<line class="axis" x1="{PAD_LEFT}" y1="{PAD_TOP + plot_h}" '
        f'x2="{width - PAD_RIGHT}" y2="{PAD_TOP + plot_h}"/>'
    )
    # 阈值参考线：Self-Loop 的 pass_threshold，一眼看出哪轮跨过
    if threshold is not None:
        ty = y_of(threshold)
        body.append(
            f'<line x1="{PAD_LEFT}" y1="{ty:.1f}" x2="{width - PAD_RIGHT}" y2="{ty:.1f}" '
            f'stroke="#e8590c" stroke-width="1.5" stroke-dasharray="6 4"/>'
        )
        body.append(
            f'<text class="value" x="{width - PAD_RIGHT}" y="{ty - 6:.1f}" '
            f'text-anchor="end" fill="#e8590c">阈值 {threshold:.2f}</text>'
        )
    points = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(values))
    body.append(f'<polyline points="{points}" fill="none" stroke="{PALETTE[0]}" stroke-width="2.5"/>')
    for i, (label, value) in enumerate(zip(labels, values)):
        cx, cy = x_of(i), y_of(value)
        body.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" fill="{PALETTE[0]}"/>')
        body.append(
            f'<text class="value" x="{cx:.1f}" y="{cy - 10:.1f}" text-anchor="middle">'
            f"{float(value):.2f}</text>"
        )
        body.append(
            f'<text class="label" x="{cx:.1f}" y="{PAD_TOP + plot_h + 18:.1f}" '
            f'text-anchor="middle">{escape(str(label))}</text>'
        )
    return _write(out, _svg(width, height, body))


def _write(out: Path, svg: str) -> Path:
    out = Path(out)
    if out.suffix.lower() != ".svg":
        raise ChartError(f"输出必须是 .svg（保持文本可 diff）：{out.name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8", newline="\n")
    return out
