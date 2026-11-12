"""生成两张流程类矢量图（Owner: B）。

    1. `docs/images/sequence.svg`      一次真实运行的节点时序（读 trace.jsonl）
    2. `docs/images/evidence-flow.svg` 证据链数据流（语料 → 引用 → 回原文）

两张都不是"示意图"：时序图的时间戳、节点顺序、轮次全部来自实际运行产物；
数据流图的每一跳都对应仓库里真实存在的函数或文件。
`tests/test_flow_svgs.py` 会对着 trace.jsonl 与代码逐项校验。

用法：
    python -m src.run --output outputs/_viz        # 先生成 trace
    python scripts/make_flow_svgs.py --trace outputs/_viz/trace.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, sans-serif"

C_INK = "#1f2933"
C_MUTED = "#5b6770"
C_LINE = "#c7d0d8"
C_R0 = "#9aa5b1"      # 第 0 轮（失败）
C_R1 = "#2f9e6f"      # 第 1 轮（通过）
C_ACCENT = "#1b5e8c"
C_WARN = "#c05621"

# DAG 顺序（与 workflows/industry_solution.yaml 一致）
NODE_ORDER = ["plan", "retrieve", "fanout", "analyze", "outline",
              "write", "verify", "gate", "review", "snap", "revise"]

NODE_ROLE = {
    "plan": "planner", "retrieve": "researcher", "fanout": "parallel",
    "analyze": "analyst", "outline": "writer", "write": "writer",
    "verify": "verifier", "gate": "condition", "review": "reviewer",
    "snap": "checkpoint", "revise": "loop",
}


def _text(x, y, s, size=12, weight="400", fill=C_INK, anchor="start"):
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{s}</text>')


def _rect(x, y, w, h, fill, stroke=C_LINE, rx=4, dash=None):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0.5):.1f}" height="{h:.1f}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1"{extra}/>')


def _arrow(x1, y1, x2, y2, color=C_ACCENT, dash=None):
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" '
            f'stroke-width="1.6" marker-end="url(#a)"{extra}/>')


def _defs() -> str:
    return (f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{C_ACCENT}"/></marker></defs>')


# ─────────────────────────────────────────────────────────────
# 1. 时序图（读真实 trace）
# ─────────────────────────────────────────────────────────────
def build_sequence(trace_path: Path) -> str:
    events = [json.loads(line) for line in
              trace_path.read_text(encoding="utf-8").strip().splitlines() if line.strip()]

    def ts(e):
        return datetime.fromisoformat(e["ts"])

    spans: dict[tuple[int, str], tuple[datetime, datetime]] = {}
    open_at: dict[tuple[int, str], datetime] = {}
    for e in events:
        key = (e["round"], e["node_id"])
        if e["kind"] == "start":
            open_at[key] = ts(e)
        elif e["kind"] == "end" and key in open_at:
            spans[key] = (open_at.pop(key), ts(e))

    t0 = min(start for start, _ in spans.values())
    t1 = max(end for _, end in spans.values())
    total_ms = max((t1 - t0).total_seconds() * 1000, 1e-3)

    nodes = [n for n in NODE_ORDER if any(k[1] == n for k in spans)]
    rounds = sorted({k[0] for k in spans})

    W = 1280
    left, right = 168, 1210
    top = 132
    row_h = 46
    H = top + len(nodes) * row_h + 96

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           _defs(), _rect(0, 0, W, H, "#ffffff", stroke="none", rx=0)]

    out.append(_text(48, 54, "一次运行的真实节点时序", 23, "700"))
    out.append(_text(48, 80,
                     f"数据来源 trace.jsonl（{len(events)} 个事件，{len(rounds)} 轮，"
                     f"总跨度 {total_ms:.0f} ms）——非示意图",
                     12.5, "400", C_MUTED))

    # 轮次图例
    lx = 48
    for r in rounds:
        color = C_R0 if r == 0 else C_R1
        out.append(_rect(lx, 100, 14, 12, color, stroke="none"))
        label = f"第 {r} 轮" + ("（fail）" if r == 0 else "（pass）")
        out.append(_text(lx + 20, 111, label, 12, "400", C_MUTED))
        lx += 20 + 11 * len(label)

    # 时间轴
    axis_y = H - 62
    out.append(f'<line x1="{left}" y1="{axis_y}" x2="{right}" y2="{axis_y}" stroke="{C_LINE}" stroke-width="1"/>')
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        x = left + (right - left) * frac
        out.append(f'<line x1="{x:.1f}" y1="{axis_y}" x2="{x:.1f}" y2="{axis_y + 5}" stroke="{C_LINE}"/>')
        out.append(_text(x, axis_y + 20, f"{total_ms * frac:.0f} ms", 10.5, "400", C_MUTED, "middle"))

    # 每个节点一行
    for i, node in enumerate(nodes):
        y = top + i * row_h
        if i % 2 == 0:
            out.append(_rect(left, y, right - left, row_h - 8, "#f8fafc", stroke="none", rx=6))
        out.append(_text(left - 12, y + 20, node, 12.5, "700", C_INK, "end"))
        out.append(_text(left - 12, y + 34, NODE_ROLE[node], 10, "400", C_MUTED, "end"))

        for r in rounds:
            key = (r, node)
            if key not in spans:
                continue
            start, end = spans[key]
            x = left + (right - left) * ((start - t0).total_seconds() * 1000 / total_ms)
            w = (right - left) * ((end - start).total_seconds() * 1000 / total_ms)
            dur = (end - start).total_seconds() * 1000
            color = C_R0 if r == 0 else C_R1
            bar_y = y + (4 if r == 0 else 18)
            out.append(_rect(x, bar_y, max(w, 3), 12, color, stroke="none", rx=3))
            if dur >= 1.0:
                out.append(_text(x + max(w, 3) + 6, bar_y + 10, f"{dur:.1f} ms", 9.5, "400", C_MUTED))

    # 定向回退标注
    if "revise" in nodes:
        y_rev = top + nodes.index("revise") * row_h
        out.append(_text(right - 10, y_rev + 30,
                         "revise = 定向回退（只重跑 write，其余结果保留）",
                         11, "400", C_WARN, "end"))

    # 轴说明放**轴线上方**：放右侧会和 "0 ms" 刻度挤在一起（渲染出来像连成一串）
    out.append(_text(48, axis_y - 10, "时间（相对首节点启动，单位毫秒）", 10.5, "400", C_MUTED))
    out.append("</svg>")
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────
# 2. 证据链数据流
# ─────────────────────────────────────────────────────────────
def build_evidence_flow() -> str:
    W, H = 1280, 660
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           _defs(), _rect(0, 0, W, H, "#ffffff", stroke="none", rx=0)]
    out.append(_text(48, 54, "证据链：从语料切片到可回原文核对", 23, "700"))
    out.append(_text(48, 80, "每一跳都对应仓库中真实存在的文件或函数；没有一环是「示意图」",
                     12.5, "400", C_MUTED))

    steps = [
        ("① 语料", ["knowledge/corpus/ 17 份", "原创转述卡", "逐条登记许可依据"]),
        ("② 切片", ["knowledge_hub.py", "跳过 front-matter", "与权利声明段", "119 → 51 片"]),
        ("③ 检索", ["BM25 + 向量双路", "RRF 融合 k=60", "score 为融合分"]),
        ("④ 证据池", ["evidence.py", "source_id 形如 kb:x", "每条带原文与哈希"]),
        ("⑤ 引用", ["writer 必须回填", "source_id", "否则 CITATION_MISSING"]),
        ("⑥ 回查", ["evidence_refs.json", "文件/字符区间/哈希", "可逐字核对"]),
    ]

    box_w, gap = 176, 26
    y = 150
    box_h = 150
    x0 = 48
    for i, (title, lines) in enumerate(steps):
        x = x0 + i * (box_w + gap)
        fill = "#eef4fb" if i % 2 == 0 else "#e9f5ef"
        out.append(_rect(x, y, box_w, box_h, fill, rx=10))
        out.append(_text(x + 14, y + 28, title, 14, "700", C_INK))
        for j, line in enumerate(lines):
            out.append(_text(x + 14, y + 54 + j * 19, line, 10.5, "400", C_MUTED))
        if i < len(steps) - 1:
            out.append(_arrow(x + box_w + 3, y + box_h / 2, x + box_w + gap - 3, y + box_h / 2))

    # 验证环
    vy = 366
    out.append(_rect(48, vy, W - 96, 96, "#fdf1e3", rx=10))
    out.append(_text(68, vy + 30, "验证环（L1 规则验证 · rule_checker.py）", 13.5, "700", C_INK))
    checks = [
        "SCHEMA_INVALID：产物是否符合契约",
        "CITATION_MISSING：有结论但无引用",
        "CITATION_UNKNOWN：引用了不存在的 source_id",
        "NUMERIC_MISMATCH：正文数字与证据不一致",
        "MISSING_SECTION：缺必备章节",
    ]
    for i, c in enumerate(checks):
        col, row = i % 2, i // 2
        out.append(_text(68 + col * 560, vy + 56 + row * 20, "· " + c, 11, "400", C_MUTED))

    # 失败回路
    out.append(_arrow(W - 150, vy, W - 150, y + box_h + 4, C_WARN, dash="6 4"))
    out.append(_text(W - 158, vy - 8, "命中区块 → 回到 ⑤ 定向重写", 11, "400", C_WARN, "end"))

    # 交付物
    dy = 496
    out.append(_rect(48, dy, W - 96, 118, "#eaf3f8", rx=10))
    out.append(_text(68, dy + 30, "落盘产物（9 件，全部进 manifest 并附 sha256）", 13.5, "700", C_INK))
    files = ["solution.md", "evidence_chain.json", "evidence_refs.json", "scorecard.json",
             "rounds.json", "trace.jsonl", "charts/scorecard.svg", "charts/convergence.svg",
             "delivery_artifact.json"]
    for i, f in enumerate(files):
        col, row = i % 3, i // 3
        out.append(_text(68 + col * 400, dy + 58 + row * 20, "· " + f, 11, "400", C_MUTED))

    out.append(_text(48, H - 18,
                     "口径：页码仅 PDF/DOCX 等分页格式有值；当前 Markdown 语料 page 为 null，"
                     "靠 file_path + char_range + hash 回原文。",
                     10.5, "400", C_MUTED))
    out.append("</svg>")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=ROOT / "outputs" / "_viz" / "trace.jsonl")
    parser.add_argument("--outdir", type=Path, default=ROOT / "docs" / "images")
    args = parser.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    seq = args.outdir / "sequence.svg"
    seq.write_text(build_sequence(args.trace), encoding="utf-8")
    print(f"[OK] 时序图  → {seq}（读 {args.trace.name}）")

    flow = args.outdir / "evidence-flow.svg"
    flow.write_text(build_evidence_flow(), encoding="utf-8")
    print(f"[OK] 证据链  → {flow}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
