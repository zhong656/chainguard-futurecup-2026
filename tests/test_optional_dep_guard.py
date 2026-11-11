"""可选依赖的导入护栏（Owner: B）。

问题
----
`tests/test_llm_adapter.py` 曾在模块顶层 `import httpx`。本机与 CI 都装了 httpx，
所以一直绿的；但**干净环境（评审解压、只装最小依赖）里 pytest 会在收集阶段报
ERROR，`check.py` 直接红**。

第一版护栏的缺陷（A 在 #84 review 里指出并复现）
------------------------------------------------
第一版只做**字符串匹配**：文件里出现 `importorskip("httpx")` 就算通过。
于是下面这种写法能骗过它：

```python
import httpx                      # 先导入 —— 干净环境在这里就炸了
import pytest
pytest.importorskip("httpx")      # 后补的 guard，救不回来
```

注释里写一句 `# 记得 importorskip("httpx")` 也能骗过。

现在的做法
----------
**AST + 行号顺序**：模块顶层的可选依赖导入，必须存在一条**在其之前执行**的
`pytest.importorskip("<同名>")`。字符串与注释不参与判断。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

# 可选依赖：装了更好，没装也必须能跑（跳过相关用例）
OPTIONAL = ("fastapi", "httpx", "uvicorn", "pymupdf", "docx", "langgraph", "chromadb",
            "fitz", "win32com", "pptx")


def _root(name: str) -> str:
    return name.split(".")[0]


def _importorskip_name(call: ast.Call) -> str | None:
    """如果是 `pytest.importorskip("x")` / `importorskip("x")`，返回 x。"""
    func = call.func
    is_attr = isinstance(func, ast.Attribute) and func.attr == "importorskip"
    is_name = isinstance(func, ast.Name) and func.id == "importorskip"
    if not (is_attr or is_name):
        return None
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def guard_lines(tree: ast.Module) -> dict[str, int]:
    """模块顶层**实际执行**的 importorskip：name → 最早行号。

    只认模块 body 里的表达式/赋值语句，注释与字符串天然不参与。
    """
    found: dict[str, int] = {}
    for node in tree.body:
        call: ast.Call | None = None
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
        if call is None:
            continue
        name = _importorskip_name(call)
        if name:
            found[name] = min(found.get(name, node.lineno), node.lineno)
    return found


def optional_imports(tree: ast.Module) -> list[tuple[str, int]]:
    """模块顶层的可选依赖导入：(模块名, 行号)。

    `try: import x / except ImportError:` 视为安全，不计入——那种写法本身
    就是"缺了也能跑"。
    """
    out: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _root(alias.name) in OPTIONAL:
                    out.append((_root(alias.name), node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if _root(node.module) in OPTIONAL:
                out.append((_root(node.module), node.lineno))
    return out


def violations(source: str) -> list[str]:
    """返回违规描述；空列表表示合规。"""
    tree = ast.parse(source)
    guards = guard_lines(tree)
    problems = []
    for name, line in optional_imports(tree):
        guard = guards.get(name)
        if guard is None:
            problems.append(
                f'第 {line} 行顶层导入 {name}，但整个模块没有 importorskip("{name}")'
            )
        elif guard > line:
            problems.append(
                f'第 {line} 行导入 {name}，而 importorskip("{name}") 在第 {guard} 行——'
                f"太晚了，干净环境会先在导入处失败"
            )
    return problems


@pytest.mark.parametrize("path", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name)
def test_optional_imports_are_guarded_before_use(path: Path):
    problems = violations(path.read_text(encoding="utf-8"))
    assert not problems, (
        f"{path.name} 存在未受保护的可选依赖导入：\n  "
        + "\n  ".join(problems)
        + '\n修法：把 pytest.importorskip("<name>") 放到该 import **之前**'
    )


# ── 护栏自身的反例测试（A 在 #84 要求补）──────────────────────
def test_repro_import_before_guard_is_flagged():
    """A 复现的反例：先 import、后 guard —— 必须报错。"""
    source = (
        "import httpx\n"
        "import pytest\n"
        "\n"
        'pytest.importorskip("httpx")\n'
        "\n"
        "def test_x():\n"
        "    pass\n"
    )
    assert violations(source), "先 import 后 guard 竟然通过了护栏"


def test_guard_before_import_passes():
    source = (
        "import pytest\n"
        "\n"
        'pytest.importorskip("httpx")\n'
        "import httpx\n"
        "\n"
        "def test_x():\n"
        "    pass\n"
    )
    assert violations(source) == []


def test_assignment_style_guard_passes():
    """`httpx = pytest.importorskip("httpx")` 也算有效（test_llm_adapter 就是这种）。"""
    source = (
        "import pytest\n"
        'httpx = pytest.importorskip("httpx")\n'
        "\n"
        "def test_x():\n"
        "    pass\n"
    )
    assert violations(source) == []


def test_comment_mentioning_importorskip_does_not_count():
    """注释里写一句 importorskip 不能骗过护栏。"""
    source = (
        "# 这里应该写 pytest.importorskip('httpx')\n"
        "import httpx\n"
        "\n"
        "def test_x():\n"
        "    pass\n"
    )
    assert violations(source), "注释里的字符串被当成了真实 guard"


def test_string_literal_mentioning_importorskip_does_not_count():
    source = (
        'NOTE = "pytest.importorskip(\'httpx\')"\n'
        "import httpx\n"
        "\n"
        "def test_x():\n"
        "    pass\n"
    )
    assert violations(source), "字符串字面量被当成了真实 guard"


def test_try_except_import_is_allowed():
    """`try: import x / except ImportError:` 本身就是缺了也能跑，不该报。"""
    source = (
        "try:\n"
        "    import httpx\n"
        "except ImportError:\n"
        "    httpx = None\n"
    )
    assert violations(source) == []


def test_guard_for_wrong_package_does_not_count():
    source = (
        "import pytest\n"
        'pytest.importorskip("fastapi")\n'
        "import httpx\n"
    )
    assert violations(source), "为别的包写了 guard 也算通过，护栏太松"


def test_guard_covers_enough_files():
    files = list(TESTS.glob("test_*.py"))
    assert len(files) >= 20, f"只扫到 {len(files)} 个测试文件，护栏可能没生效"


def test_test_api_uses_importorskip():
    """回归样例：test_api.py 是正确写法，别被人改回去。"""
    source = (TESTS / "test_api.py").read_text(encoding="utf-8")
    assert 'importorskip("fastapi"' in source
    assert 'importorskip("httpx"' in source
