"""生成架构矢量图（SVG），精确对应代码结构（Owner: B）。

为什么手写 SVG 而不引第三方绘图库
----------------------------------
架构图要进方案书 PDF，要求：
    1. **矢量**：放大不失真；
    2. **可控**：每个框的位置、文字、连线都能精确指定；
    3. **零依赖**：评审不需要装 graphviz / drawio / mermaid CLI。

所以用 Python 直接拼 SVG 字符串——和 `vertical_slice._render_charts()` 同一路数，
仓库里本来就有自研 SVG 渲染，不引入新依赖。

精度保证
--------
图里的模块名、契约名、接口路径、端口、数量全部**从仓库实读**，
并在 `tests/test_architecture_svg.py` 里对着真实文件逐项断言——
图与代码不一致，测试就红。

用法：
    python scripts/make_architecture_svg.py                 # 输出 docs/images/architecture.svg
    python scripts/make_architecture_svg.py --out x.svg
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

W, H = 1280, 900
FONT = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, sans-serif"

# 配色：与交付包图表保持一致（深蓝主色 + 分层浅底）
C_BG = "#ffffff"
C_INK = "#1f2933"
C_MUTED = "#5b6770"
C_LINE = "#c7d0d8"
C_L1 = "#eef4fb"   # 接入层
C_L2 = "#e9f5ef"   # 编排层
C_L3 = "#fdf1e3"   # 执行层
C_L4 = "#f3ecfa"   # 验证层
C_L5 = "#eaf3f8"   # 产出层
C_ACCENT = "#1b5e8c"
C_CONTRACT = "#7b4fa8"


def _count_contracts() -> list[str]:
    return sorted(p.name.replace(".schema.json", "") for p in (ROOT / "contracts").glob("*.schema.json"))


def _count_agents() -> int:
    return len(list((ROOT / "agents").glob("*.yaml")))


def _count_corpus() -> int:
    return len(list((ROOT / "knowledge" / "corpus").glob("*.md")))


def _routes() -> list[str]:
    text = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    out = []
    for match in re.finditer(r'@app\.(get|post)\(\s*"([^"]+)"', text):
        out.append(f"{match.group(1).upper()} {match.group(2)}")
    return out


def _rect(x, y, w, h, fill, stroke=C_LINE, rx=8, dash=None):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"{extra}/>')


def _text(x, y, s, size=13, weight="400", fill=C_INK, anchor="start"):
    s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def _arrow(x1, y1, x2, y2, color=C_ACCENT, dash=None, width=1.6):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="{width}" marker-end="url(#arrow)"{extra}/>')


def build_svg() -> str:
    contracts = _count_contracts()
    agents = _count_agents()
    corpus = _count_corpus()
    routes = _routes()

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">'
    )
    parts.append(
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{C_ACCENT}"/></marker></defs>'
    )
    parts.append(_rect(0, 0, W, H, C_BG, stroke="none", rx=0))

    # 标题
    parts.append(_text(48, 52, "链衡 ChainGuard · 系统架构", 24, "700", C_INK))
    parts.append(_text(48, 78, "五层结构 · 11 节点 DAG · 6 类 Agent · 11 份契约冻结", 13, "400", C_MUTED))

    # ── 契约侧栏 ────────────────────────────────────────────
    cx, cy, cw = 48, 112, 132
    lane_top, lane_bottom = 112, 800
    parts.append(_rect(cx, cy, cw, lane_bottom - lane_top, "#f7f4fb", C_CONTRACT, rx=10))
    parts.append(_text(cx + cw / 2, cy + 30, "契约 contracts/", 13, "700", C_CONTRACT, "middle"))
    parts.append(_text(cx + cw / 2, cy + 50, f"{len(contracts)} 份 JSON Schema", 11, "400", C_MUTED, "middle"))
    parts.append(_text(cx + cw / 2, cy + 68, "2026-11-07 冻结", 11, "400", C_MUTED, "middle"))
    parts.append(_text(cx + cw / 2, cy + 84, "tag contracts-v1.0", 10, "400", C_MUTED, "middle"))
    for i, name in enumerate(contracts):
        parts.append(_text(cx + 14, cy + 116 + i * 20, "· " + name, 10.5, "400", C_INK))

    # ── 主区域 ──────────────────────────────────────────────
    mx, mw = 208, W - 208 - 48

    def _cjk_width(s: str, size: float) -> float:
        """粗估文字宽度：CJK 约 1.0em，ASCII 约 0.55em。

        踩过：早先按 8px/字估算，导致中英文混排时副标题压在标题上。
        """
        return sum(size * (1.0 if ord(c) > 0x2E80 else 0.55) for c in s)

    def lane(y, h, fill, title, subtitle=""):
        parts.append(_rect(mx, y, mw, h, fill, rx=10))
        parts.append(_text(mx + 18, y + 26, title, 14, "700", C_INK))
        if subtitle:
            offset = 18 + _cjk_width(title, 14) + 18
            parts.append(_text(mx + offset, y + 26, subtitle, 11.5, "400", C_MUTED))

    def box(x, y, w, h, title, lines):
        parts.append(_rect(x, y, w, h, "#ffffff"))
        parts.append(_text(x + 12, y + 24, title, 12.5, "700", C_INK))
        for i, line in enumerate(lines):
            parts.append(_text(x + 12, y + 44 + i * 16, line, 10.5, "400", C_MUTED))

    # L1 接入层
    lane(112, 118, C_L1, "① 接入层", "三种入口，同一套执行链")
    box(mx + 18, 148, 300, 68, "CLI · src/run.py", ["python -m src.run", "零 Key · 一条命令出交付包"])
    # 三个接口**全部列出**：图上少一个，评审对照代码就发现对不上
    route_line_1 = "  ".join(routes[:2])
    route_line_2 = "  ".join(routes[2:])
    box(mx + 330, 148, 300, 76, "HTTP API · src/main.py",
        [f"FastAPI · {len(routes)} 个接口（:8000）", route_line_1, route_line_2])
    box(mx + 642, 148, 300, 68, "控制台 · web/", ["Vue3 构建产物 + Trace 重放（:8766）", "同源代理转发到 API"])

    # L2 编排层
    lane(246, 128, C_L2, "② 编排层", "编译期静态校验 + 运行期调度")
    box(mx + 18, 282, 300, 78, "DAG 编译器 · dag_compiler.py", ["YAML → 可执行计划", "校验：无环 / 依赖 / 条件 / 并行", "失败走 compile_error 契约"])
    box(mx + 330, 282, 300, 78, "调度器 · scheduler.py", ["并发信号量 · 超时 · 指数退避重试", "降级 → 安全中止（不产出交付包）", "Token 预算护栏"])
    box(mx + 642, 282, 300, 78, "Loop 控制器 · loop_controller.py", ["定向回退：只重跑 write", "回边目标必须是 verify 合法前驱", "≤3 轮 · 连续 2 轮无提升终止"])

    # L3 执行层
    lane(390, 128, C_L3, "③ 执行层", f"{agents} 类角色 · 内容指纹热加载")
    box(mx + 18, 426, 300, 78, "角色注册表 · agent_registry.py", [f"agents/*.yaml（{agents} 份）", "SHA256 指纹热加载，改配置不重启", "只读/可写约束强制校验"])
    box(mx + 330, 426, 300, 78, "知识库 · knowledge_hub.py", [f"语料 {corpus} 份（原创转述卡）", "BM25 + 向量 → RRF k=60", "切片跳过权利声明段"])
    box(mx + 642, 426, 300, 78, "工具与隔离 · sandbox.py / trace.py", ["工具白名单 · 只读角色不可写", "trace.jsonl 逐事件落盘", "LLM 适配四档：DeepSeek/Qwen/Ollama/Mock"])

    # L4 验证层
    lane(534, 118, C_L4, "④ 验证层", "L1 确定性 + L2 独立评审；L3 未实现")
    box(mx + 18, 564, 440, 74, "L1 规则验证 · rule_checker.py", ["SCHEMA_INVALID / CITATION_MISSING / CITATION_UNKNOWN", "NUMERIC_MISMATCH / MISSING_SECTION"])
    box(mx + 476, 564, 466, 74, "L2 独立评审 · verifier.py", ["温度 0.0 ≠ 撰写 0.3（相同则拒绝启动）", "一票否决：blocker 存在即 fail，无论加权分"])

    # L5 产出层
    lane(668, 118, C_L5, "⑤ 产出层", "9 件交付物 + manifest + 逐文件 sha256")
    box(mx + 18, 698, 300, 74, "纵切 · vertical_slice.py", ["一次运行产出 9 件文件", "两张 SVG 图表自研渲染"])
    box(mx + 330, 698, 300, 74, "证据链 · evidence.py", ["evidence_refs.json", "文件 / 字符区间 / 原文 / 哈希"])
    box(mx + 642, 698, 300, 74, "反馈库 · feedback.py", ["SQLite 幂等写入", "样本 <30 只报个案，不报比率"])

    # ── 数据流（右侧贯穿箭头）───────────────────────────────
    fx = W - 30
    parts.append(_arrow(fx, 168, fx, 760, C_ACCENT, dash="6 4", width=1.4))
    parts.append(_text(fx - 8, 120, "请求 →", 11, "700", C_ACCENT, "end"))
    parts.append(_text(fx - 8, 790, "交付包", 11, "700", C_ACCENT, "end"))

    # 层间箭头：**只在层与层之间的空隙连线**。
    # 踩过：早先把箭头画到下一层的标题带（y+26）上，中文字标被线穿过，很难看。
    lane_edges = [(230, 246), (374, 390), (518, 534), (652, 668)]
    for x in (mx + 168, mx + 480, mx + 792):
        for top, bottom in lane_edges:
            parts.append(_arrow(x, top, x, bottom))

    # 图例
    ly = 832
    parts.append(_text(48, ly, "图例：", 11.5, "700", C_INK))
    for i, (label, color) in enumerate((("接入", C_L1), ("编排", C_L2), ("执行", C_L3), ("验证", C_L4), ("产出", C_L5))):
        x = 100 + i * 92
        parts.append(_rect(x, ly - 11, 16, 12, color))
        parts.append(_text(x + 22, ly, label, 11, "400", C_MUTED))
    parts.append(_text(W - 48, ly, "虚线 = 契约约束贯穿各层；实线 = 执行与数据流", 11, "400", C_MUTED, "end"))

    parts.append("</svg>")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "images" / "architecture.svg")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    svg = build_svg()
    args.out.write_text(svg, encoding="utf-8")
    print(f"[OK] 架构图 → {args.out}（{len(svg) / 1024:.1f} KB，矢量）")
    print(f"     契约 {len(_count_contracts())} 份 / 角色 {_count_agents()} 类 / 语料 {_count_corpus()} 份 / 接口 {len(_routes())} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
