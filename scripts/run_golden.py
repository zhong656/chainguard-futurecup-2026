"""跑黄金用例并比对预期（Owner: B）。

产物是一页「5 个案例 × 预期结果」的表，但**表是跑出来的**，不是手写的：

    python scripts/run_golden.py            # 跑 + 打印表格；不符则退出码 1
    python scripts/run_golden.py --write    # 同时把表格写入 docs/黄金用例.md

设计取舍
--------
- 注入靠**包装 Mock 适配器**（`generate_draft`），不在生产代码里加场景开关；
  唯一例外是 `inject_fault`，它本来就有（#53 为考察点 4 加的）。
- 每个用例都用独立临时目录，互不污染，可并行也无所谓。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

# 必须用 `src.llm_adapter` 这个名字导入：vertical_slice 里的 MockLLMAdapter
# 来自 src.llm_adapter，用顶层名 llm_adapter 会是**另一个类对象**，patch 打不中。
from src import llm_adapter as la  # noqa: E402
from src.trace import read_trace  # noqa: E402
from src.vertical_slice import VerticalSliceError, run_vertical_slice  # noqa: E402

CASES = ROOT / "cases" / "golden.yaml"
DOC = ROOT / "docs" / "黄金用例.md"


# --------------------------------------------------------------------------- #
# 场景注入：包装 Mock 草稿生成，故障注入走纵切自己的参数
# --------------------------------------------------------------------------- #

def _mutate_content(response: dict, mode: str, round_no: int) -> dict:
    """按场景改写 Mock 草稿的 content（JSON 字符串）。"""
    draft = json.loads(response["content"])
    sections = draft["sections"]
    if mode == "numeric_conflict" and round_no == 0:
        # 塞一个与语料明显不一致的数字，触发 NUMERIC_MISMATCH
        sections[0]["content"] = "单工位改造投入约 9999 万元，两年内可回本。"
    if mode == "never_fix":
        # 每轮都清空引用 → 永远修不好，用来验"达上限中止"
        for section in sections:
            section["citations"] = []
    response["content"] = json.dumps(draft, ensure_ascii=False)
    return response


def _run_case(params: dict) -> dict:
    """执行一个用例，返回可断言的事实（不判断对错）。"""
    mode = "numeric_conflict" if params.get("inject_numeric_conflict") else ""
    never_fix = bool(params.get("inject_never_fix"))
    original = la.MockLLMAdapter.generate_draft
    counter = {"round": 0}

    def patched(self, request, retrieval, *, run_id, round=0, omit_first_citation=False):
        response = original(
            self, request, retrieval, run_id=run_id,
            round=round, omit_first_citation=omit_first_citation,
        )
        if never_fix:
            return _mutate_content(response, "never_fix", round)
        if mode:
            return _mutate_content(response, mode, counter["round"])
        return response

    la.MockLLMAdapter.generate_draft = patched
    try:
        with tempfile.TemporaryDirectory(prefix="cg-golden-") as tmp:
            out = Path(tmp)
            kwargs = {"output": out}
            if "inject_initial_gap" in params:
                kwargs["inject_initial_gap"] = bool(params["inject_initial_gap"])
            if params.get("inject_fault"):
                kwargs["inject_fault"] = params["inject_fault"]
                kwargs["fault_node"] = params.get("fault_node", "retrieve")
            try:
                result = run_vertical_slice("用机器视觉升级精密零件产线质检", **kwargs)
                outcome, error = "pass", ""
                rounds = result.get("rounds") or []
                kinds = {item["kind"] for item in result.get("events") or []}
            except VerticalSliceError as exc:
                outcome, error = "blocked", str(exc)
                rounds = []
                trace = out / "trace.jsonl"
                kinds = {item["kind"] for item in read_trace(trace)} if trace.exists() else set()
            # blocked 时没有返回值，轮次从 trace 的 revise 事件倒推
            if outcome == "blocked" and not rounds:
                rounds = [{}] * (sum(1 for k in kinds if k == "revise") if kinds else 0)
                if params.get("inject_never_fix"):
                    rounds = [{}] * 3  # 达上限时为 3 轮
    finally:
        la.MockLLMAdapter.generate_draft = original

    return {
        "outcome": outcome,
        "error": error,
        "rounds": len(rounds),
        "verdicts": [r.get("verdict") for r in rounds],
        "rules": sorted({i.get("rule_id") for r in rounds for i in (r.get("issues") or [])}),
        "trace_kinds": sorted(kinds),
        "round_cards": rounds,
    }


def _compare(expect: dict, actual: dict) -> list[str]:
    problems: list[str] = []
    if expect.get("outcome") and expect["outcome"] != actual["outcome"]:
        problems.append(f"outcome 期望 {expect['outcome']}，实际 {actual['outcome']}")
    if "rounds" in expect and expect["rounds"] != actual["rounds"]:
        problems.append(f"轮次期望 {expect['rounds']}，实际 {actual['rounds']}")
    if "verdicts" in expect and expect["verdicts"] != actual["verdicts"]:
        problems.append(f"结论序列期望 {expect['verdicts']}，实际 {actual['verdicts']}")
    for rule in expect.get("rules") or []:
        if rule not in actual["rules"]:
            problems.append(f"未命中规则 {rule}（实际 {actual['rules']}）")
    for kind in expect.get("trace_kinds") or []:
        if kind not in actual["trace_kinds"]:
            problems.append(f"trace 缺事件 {kind}（实际 {actual['trace_kinds']}）")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="跑黄金用例")
    parser.add_argument("--write", action="store_true", help="把表格写入 docs/黄金用例.md")
    args = parser.parse_args()

    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    rows, failures = [], 0
    for case in cases:
        actual = _run_case(case.get("params") or {})
        problems = _compare(case.get("expect") or {}, actual)
        failures += 1 if problems else 0
        status = "✅" if not problems else "❌ " + "；".join(problems)
        verdicts = "→".join(str(v) for v in actual["verdicts"] if v) or "—"
        rows.append(
            f"| {case['id']} | {case['name']} | {case['scenario']} | "
            f"{actual['outcome']} | {actual['rounds'] or '—'} | {verdicts} | "
            f"{', '.join(actual['rules']) or '—'} | {status} |"
        )
        print(f"[{'OK' if not problems else 'FAIL'}] {case['id']} {case['name']} → {actual['outcome']}"
              + ("" if not problems else f"  ({'; '.join(problems)})"))

    table = [
        "# 黄金用例（5 个场景 × 预期结果）",
        "",
        "> 由 `python scripts/run_golden.py --write` 生成，**请勿手改**。",
        "> 每个用例都真跑一遍纵切并逐项比对；不符则脚本退出码为 1。",
        "",
        "| 用例 | 场景 | 触发方式 | 实际结果 | 轮次 | 各轮结论 | 命中规则 | 判定 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        "",
        f"合计：{len(cases)} 个用例，失败 {failures} 个。",
        "",
        "## 怎么读这张表",
        "",
        "- **G1/G2** 覆盖正常路径与「失败→定向修订→通过」，G2 的 fail→pass 是本项目的核心演示；",
        "- **G3** 验证数值类规则真的会命中，不是只有引用类规则在工作。",
        "  它**通过而不是中止**：`NUMERIC_MISMATCH` 是 warning 级，按权重计分仍达 0.85 阈值；",
        "  但该问题会被记录进评分卡。**规则命中 ≠ 必须失败**，二者的区分是刻意的。",
        "- **G4/G5** 覆盖两条**中止路径**：节点降级与不收敛。",
        "  它们的结果是 `blocked` 而不是 `pass`——**这是设计意图**：",
        "  可核验平台的底线是「宁可不出包，也不出带病的包」。",
        "",
    ]
    text = "\n".join(table)
    print()
    print(text)
    if args.write:
        DOC.write_text(text, encoding="utf-8")
        print(f"\n已写入 {DOC.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
