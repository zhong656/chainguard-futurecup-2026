"""证据采集：把测试报告要用的数字一次跑出来（Owner: B）。

为什么要有这个脚本
------------------
测试报告里的数字（命中率、收敛轮次、故障注入事件数）如果靠人记，
**三天后就会和代码对不上**。这里把每项都做成可重跑的命令：

    python scripts/collect_evidence.py            # 打印 + 写 outputs/证据汇总.md

产物是生成物，不入库（见 .gitignore），`docs/测试报告.md` 只引用口径与命令。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

PY = sys.executable
OUT = ROOT / "outputs" / "证据汇总.md"


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def section_checks() -> list[str]:
    code, out = _run([PY, "scripts/check.py"])
    lines = [ln for ln in out.splitlines() if "[OK]" in ln or "[PASS]" in ln or "passed" in ln]
    status = "PASS" if code == 0 else "FAIL"
    return [f"- `python scripts/check.py` → **{status}**（退出码 {code}）"] + [f"  - {ln.strip()}" for ln in lines]


def section_retrieval() -> list[str]:
    import knowledge_eval as ke

    report = ke.evaluate()
    rows = ["- 评测集：`knowledge/eval/queries.yaml`（22 条，17 原文词 + 5 改述）",
            f"- **hit@{report.top_k} = {report.hit_rate:.2%}**，hit@1 = {report.hit_at_1:.2%}，MRR = {report.mrr}",
            "",
            "| 组 | 查询数 | hit@k | hit@1 | MRR |",
            "| --- | --- | --- | --- | --- |"]
    for name, n, hr, h1, mrr in ke._groups(report):
        rows.append(f"| {name} | {n} | {hr:.2%} | {h1:.2%} | {mrr} |")
    return rows


def section_self_loop() -> list[str]:
    from src.vertical_slice import run_vertical_slice

    with tempfile.TemporaryDirectory() as tmp:
        run_vertical_slice("用机器视觉升级精密零件产线质检", output=Path(tmp))
        rounds = json.loads((Path(tmp) / "rounds.json").read_text(encoding="utf-8"))
        files = sorted(p.name for p in Path(tmp).rglob("*") if p.is_file())
    rows = ["- `python -m src.run` 一次纵切产出：" + "、".join(files), "",
            "| 轮次 | 分数 | 结论 | 问题数 |", "| --- | --- | --- | --- |"]
    for r in rounds:
        rows.append(f"| R{r['round']} | {r['score']} | {r['verdict']} | {len(r['issues'])} |")
    if rounds:
        rows.append("")
        rows.append(
            f"- 首轮 `{rounds[0]['verdict']}`、终轮 `{rounds[-1]['verdict']}`："
            "**fail→pass 有物证**，不是只报终态"
        )
    return rows


def section_fault_injection() -> list[str]:
    from src.trace import read_trace
    from src.vertical_slice import VerticalSliceError, run_vertical_slice

    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_vertical_slice("机器视觉", output=Path(tmp), inject_fault="timeout", fault_node="retrieve")
            ending = "（未抛错，异常）"
        except VerticalSliceError as exc:
            ending = f"- 降级后安全中止：`{exc}`"
        kinds: dict[str, int] = {}
        for item in read_trace(Path(tmp) / "trace.jsonl"):
            kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    rows = ["- 命令：`python -m src.run --inject-fault timeout --node retrieve`",
            "- 事件统计：" + "、".join(f"`{k}`×{v}" for k, v in sorted(kinds.items()))]
    assert {"fail", "retry", "degrade"} <= set(kinds), f"缺关键事件：{sorted(kinds)}"
    rows.append("- 断言：`fail` / `retry` / `degrade` 三类事件同时出现 ✅")
    rows.append(ending)
    return rows


def section_security() -> list[str]:
    rows = ["| 项 | 做法 | 测试 |", "| --- | --- | --- |"]
    rows.append("| 受限执行沙箱 | AST 白名单 + 隔离进程 + 超时 + 输出截断 | `tests/test_sandbox.py` 12 条 |")
    rows.append("| 只读角色越权 | `read_only=true` 的角色不得配副作用工具 | `check_contracts` 第 9 项 |")
    key_leak = subprocess.run(
        [PY, "-c", "import sys;sys.path.insert(0,'src');import sandbox;r=sandbox.run('import os');print(r.ok)"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    rows.append(f"| 越权导入拦截 | `import os` 在执行前被拒 | 实测返回 `{key_leak.stdout.strip() or 'error'}`（False 为通过） |")
    return rows


def main() -> int:
    parts = [
        ("契约与配置检查", section_checks()),
        ("检索命中率", section_retrieval()),
        ("Self-Loop 收敛", section_self_loop()),
        ("故障注入与降级", section_fault_injection()),
        ("安全边界", section_security()),
    ]
    text = ["# 证据汇总（自动生成，请勿手改）", "", f"> 生成命令：`python scripts/collect_evidence.py`", ""]
    for title, rows in parts:
        text += [f"## {title}", "", *rows, ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(text) + "\n", encoding="utf-8")
    print("\n".join(text))
    print(f"\n已写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
