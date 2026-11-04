#!/usr/bin/env python3
"""唯一检查入口。本地与 CI 跑的是同一个文件、同一套步骤。

    python scripts/check.py        # 等价于 make check

步骤（任一失败即非零退出）：
    1. 语  法：scripts/ 与 src/ 下的 Python 文件可解析
    2. 契  约：scripts/check_contracts.py（含 $ref、配置、归属、依赖）
    3. 测  试：pytest -q tests/
    4. 冒  烟：scripts/mock_e2e.py（产物须通过 delivery_artifact 契约）
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(title: str, cmd: list[str]) -> bool:
    print(f"\n=== {title} ===")
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT)  # noqa: S603
    if proc.returncode != 0:
        print(f"[FAIL] {title} 失败（exit {proc.returncode}）")
        return False
    print(f"[OK] {title} 通过")
    return True


def check_syntax() -> bool:
    files = sorted(ROOT.glob("scripts/*.py")) + sorted(ROOT.glob("src/**/*.py"))
    bad = 0
    for f in files:
        try:
            ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"[FAIL] {f.relative_to(ROOT)}: {exc}")
            bad += 1
    if bad:
        return False
    print(f"[OK] 语法检查：{len(files)} 个文件")
    return True


def main() -> int:
    steps = [
        ("语法检查", check_syntax),
        ("契约与一致性", lambda: run("契约与一致性", [PY, "scripts/check_contracts.py"])),
        ("单元测试", lambda: run("单元测试", [PY, "-m", "pytest", "-q", "tests"])),
        ("Mock 端到端", lambda: run("Mock 端到端", [PY, "scripts/mock_e2e.py"])),
    ]
    failed = []
    for title, fn in steps:
        if not fn():
            failed.append(title)
    print("\n" + "=" * 48)
    if failed:
        print(f"[FAIL] check 失败：{', '.join(failed)}")
        return 1
    print("[PASS] check 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
