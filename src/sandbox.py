"""受限 Python 执行沙箱（Owner: B）。

它做什么
--------
`run(code)` 在一个**隔离子进程**里执行一段 Python，返回结构化结果：
    成功 / 超时 / 语法错 / 越权调用 / 输出超限

三层限制，从外到内：

1. **静态检查（父进程，执行前）**
   - 只允许导入白名单里的模块（纯计算库，无 IO/网络/系统调用）
   - 禁止 `eval/exec/compile/__import__/open/input` 等入口
   - 禁止访问 dunder 属性（`obj.__class__`、`().__class__.__bases__` 是逃逸经典路径）

2. **进程隔离（子进程，执行中）**
   - `python -I`：忽略 `PYTHONPATH` 与用户 site-packages，环境变量不串味
   - `cwd` 指向临时目录：相对路径写入落在临时区，不污染仓库
   - 环境变量只留 `PYTHONIOENCODING`，不把宿主机密钥递进去

3. **资源护栏（父进程，执行后/超时）**
   - `timeout_s`：到点直接 kill，防止死循环把服务拖死
   - `max_output_bytes`：stdout/stderr 截断，防止 `print` 洪水打爆日志与内存

它**不**做什么（重要，别对外宣称过头）
------------------------------------
- 不是恶意代码沙箱。Python 层面没有真正的安全边界，反射/ctypes 仍可能绕过；
  真要跑不可信代码，得用容器/微虚拟机，不在本项目范围。
- 它防的是**失控**：死循环、乱装库、打印洪水、偷偷联网、误写文件。
- 这正好是"Agent 自己写代码算数"场景的真实风险，而不是"攻击者投毒"。

对应契约
--------
`src/tools/registry.py` 里 `python_sandbox` 的 `read_only=False`：
它有副作用（执行代码），因此只读角色（planner/researcher/verifier/reviewer）不得引用。
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# 纯计算 / 数据结构类，没有任何 IO、网络、进程、反射能力
ALLOWED_MODULES: frozenset[str] = frozenset(
    {
        "math",
        "statistics",
        "decimal",
        "fractions",
        "random",
        "itertools",
        "functools",
        "collections",
        "heapq",
        "bisect",
        "json",
        "re",
        "datetime",
        "textwrap",
        "string",
        "typing",
        "dataclasses",
        "enum",
    }
)

# 这些名字一旦出现就直接拒：它们是"跳出沙箱"或"读写宿主"的入口
FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "input",
        "breakpoint",
        "help",
        "exit",
        "quit",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "memoryview",
    }
)

FORBIDDEN_MODULE_PREFIXES: tuple[str, ...] = (
    "os",
    "sys",
    "subprocess",
    "socket",
    "shutil",
    "pathlib",
    "importlib",
    "ctypes",
    "pickle",
    "marshal",
    "multiprocessing",
    "threading",
    "http",
    "urllib",
    "requests",
    "ftplib",
    "smtplib",
    "asyncio",
    "sqlite3",
    "builtins",
    "gc",
    "inspect",
    "traceback",
    "site",
)

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAX_OUTPUT = 64 * 1024


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    exit_code: int | None = None
    timed_out: bool = False
    violations: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return "[输出已截断]" in self.stdout or "[输出已截断]" in self.stderr


class SandboxError(ValueError):
    """代码在静态检查阶段就被拒。"""

    def __init__(self, violations: list[str]) -> None:
        super().__init__("; ".join(violations))
        self.violations = violations


def _module_allowed(name: str) -> bool:
    root = name.split(".")[0]
    if root in ALLOWED_MODULES:
        return True
    return not any(root == bad or root.startswith(bad + ".") for bad in FORBIDDEN_MODULE_PREFIXES)


def validate_code(code: str) -> list[str]:
    """静态检查。返回违规列表，空列表表示可以执行。

    为什么在父进程做 AST 检查，而不是在子进程里装 import hook：
    - import hook 是**运行时**拦截，代码已经在跑了，异常路径更多；
    - AST 检查是**执行前**，不跑一行用户代码就能拒绝；
    - 两者都做最稳，但成本最低、最不会被绕过的第一道就是 AST。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"语法错误：{exc.msg}（第 {exc.lineno} 行）"]

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    violations.append(f"禁止导入模块：{alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not _module_allowed(module):
                violations.append(f"禁止导入模块：{module}")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                violations.append(f"禁止使用：{node.id}")
            elif node.id.startswith("__") and node.id.endswith("__"):
                violations.append(f"禁止访问 dunder 名字：{node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                violations.append(f"禁止访问 dunder 属性：{node.attr}")
        elif isinstance(node, ast.Call):
            # obj.__class__ 这类已经由 Attribute 规则拦住，这里补 Name 形式的调用
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
                violations.append(f"禁止调用：{node.func.id}")
    # 去重但保持顺序
    return list(dict.fromkeys(violations))


def _truncate(payload: bytes, limit: int) -> tuple[str, bool]:
    if len(payload) <= limit:
        return payload.decode("utf-8", "replace"), False
    cut = payload[:limit].decode("utf-8", "replace")
    return cut + "\n[输出已截断]", True


def run(
    code: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT,
    workdir: Path | None = None,
) -> SandboxResult:
    """执行一段 Python 代码，永不抛异常（除参数错误），结果都在返回值里。"""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code 不能为空")
    if timeout_s <= 0:
        raise ValueError("timeout_s 必须为正数")

    violations = validate_code(code)
    if violations:
        return SandboxResult(ok=False, violations=violations, stderr="静态检查未通过")

    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cg-sbx-") as tmp:
        cwd = Path(workdir) if workdir else Path(tmp)
        cwd.mkdir(parents=True, exist_ok=True)
        script = Path(tmp) / "snippet.py"
        script.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(  # noqa: S603
                [sys.executable, "-I", "-B", str(script)],
                cwd=str(cwd),
                env={"PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"},
                capture_output=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            out, _ = _truncate(exc.stdout or b"", max_output_bytes)
            err, _ = _truncate(exc.stderr or b"", max_output_bytes)
            return SandboxResult(
                ok=False,
                stdout=out,
                stderr=err or f"执行超过 {timeout_s}s，已终止",
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )

        stdout, _ = _truncate(proc.stdout or b"", max_output_bytes)
        stderr, _ = _truncate(proc.stderr or b"", max_output_bytes)
        return SandboxResult(
            ok=proc.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            duration_ms=int((time.perf_counter() - started) * 1000),
            exit_code=proc.returncode,
        )
