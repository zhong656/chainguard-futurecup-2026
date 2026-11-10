"""可选依赖的导入护栏（Owner: B）。

问题
----
`tests/test_llm_adapter.py` 曾在模块顶层 `import httpx`。本机与 CI 都装了 httpx，
所以一直绿的；但**干净环境（评审解压、只装最小依赖）里 pytest 会在收集阶段报
ERROR，`check.py` 直接红**。

这类问题的共性是：**本地有依赖 → 绿灯；没依赖 → 红**，而 CI 恰好装了依赖，
所以只能在"别人的机器"上暴露。

本护栏的做法
------------
静态扫描 `tests/`：凡在**模块顶层**导入可选依赖（fastapi / httpx / uvicorn /
pymupdf / docx / langgraph / chromadb），就必须同时出现
`pytest.importorskip("<name>")`——否则报错。

这样新增测试时写错导入，CI 会立刻拦下，而不是等别人在干净环境里踩。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# 可选依赖：装了更好，没装也必须能跑（跳过相关用例）
OPTIONAL = ("fastapi", "httpx", "uvicorn", "pymupdf", "docx", "langgraph", "chromadb")


def _top_level_imports(tree: ast.Module) -> set[str]:
    """只看模块顶层（col_offset == 0）的导入。"""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("path", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name)
def test_optional_imports_are_guarded(path: Path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    tops = _top_level_imports(tree)
    risky = sorted(n for n in tops if n in OPTIONAL)
    if not risky:
        return
    guarded = set(re.findall(r'importorskip\(\s*["\']([\w.]+)["\']', source))
    unguarded = [n for n in risky if n not in guarded]
    assert not unguarded, (
        f"{path.name} 在模块顶层导入了可选依赖 {unguarded} 却没有 importorskip —— "
        f"干净环境（无 {unguarded}）下 pytest 收集阶段会 ERROR，check.py 会红。\n"
        f'修法：import pytest; pytest.importorskip("{unguarded[0]}")'
    )


def test_guard_covers_known_files():
    """护栏本身要有覆盖面：至少检查到十几个测试文件。"""
    files = list(TESTS.glob("test_*.py"))
    assert len(files) >= 15, f"只扫到 {len(files)} 个测试文件，护栏可能没生效"


def test_test_api_uses_importorskip():
    """回归样例：test_api.py 是正确写法，别被人改回去。"""
    source = (TESTS / "test_api.py").read_text(encoding="utf-8")
    assert 'importorskip("fastapi"' in source
    assert 'importorskip("httpx"' in source
