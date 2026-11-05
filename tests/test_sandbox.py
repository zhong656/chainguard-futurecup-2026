"""沙箱的边界测试（Owner: B）。

这些用例的重点不是"能算对"，而是**该拒的必须拒、该停的必须停**：
    1. 正常计算能跑通
    2. 死循环会被 timeout 杀掉（且返回 timed_out，不抛异常）
    3. 越权导入 / dunder 访问 / open 在**执行前**就被拒
    4. 输出洪水会被截断
    5. 子进程拿不到宿主环境变量（隔离验证）
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import sandbox  # noqa: E402


def test_simple_compute_ok():
    result = sandbox.run("print(sum(range(10)))")
    assert result.ok
    assert result.stdout.strip() == "45"
    assert result.exit_code == 0


def test_allowed_imports_work():
    result = sandbox.run("import math, statistics\nprint(round(math.sqrt(16)), int(statistics.mean([1,2,3])))")
    assert result.ok, result.stderr
    assert result.stdout.split() == ["4", "2"]


def test_timeout_kills_loop():
    """死循环必须被终止，而不是把调用方挂住。"""
    result = sandbox.run("while True:\n    pass\n", timeout_s=1.0)
    assert not result.ok
    assert result.timed_out
    assert result.duration_ms < 5000


def test_forbidden_import_rejected_before_run():
    result = sandbox.run("import os\nprint(os.getcwd())")
    assert not result.ok
    assert result.timed_out is False
    assert any("禁止导入模块" in v for v in result.violations)


def test_forbidden_import_network():
    for code in ("import socket", "import urllib.request", "from http import client"):
        result = sandbox.run(code)
        assert not result.ok, code
        assert result.violations, code


def test_open_rejected():
    result = sandbox.run("f = open('x.txt', 'w')")
    assert not result.ok
    assert any("open" in v for v in result.violations)


def test_dunder_escape_rejected():
    """`().__class__.__bases__` 是经典逃逸路径，必须在静态阶段拦住。"""
    result = sandbox.run("print((1).__class__.__bases__)")
    assert not result.ok
    assert any("dunder" in v for v in result.violations)


def test_output_truncated():
    result = sandbox.run("print('x' * 100000)", max_output_bytes=1024)
    assert not result.ok
    assert result.truncated
    assert len(result.stdout) < 5000


def test_env_not_leaked(monkeypatch):
    """宿主机环境变量不应出现在子进程里（隔离性）。"""
    monkeypatch.setenv("CHAIN_GUARD_SECRET", "top-secret")
    original_popen = sandbox.subprocess.Popen
    passed_env = {}

    def record_env(*args, **kwargs):
        passed_env.update(kwargs["env"])
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(sandbox.subprocess, "Popen", record_env)
    assert sandbox.run("print('ok')").ok
    assert set(passed_env) == {"PYTHONIOENCODING", "PYTHONHASHSEED"}
    assert "CHAIN_GUARD_SECRET" not in passed_env


def test_default_deny_imports_and_module_escape(tmp_path):
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("outside-cwd-readable", encoding="utf-8")
    cases = (
        f"import io; print(io.open({str(sentinel)!r}).read())",
        "import zipfile",
        "import random; print(random._os.getcwd())",
        "from random import _os",
        "from typing import sys",
    )
    for code in cases:
        result = sandbox.run(code)
        assert not result.ok and result.violations, code
        assert "outside-cwd-readable" not in result.stdout


def test_workdir_cannot_escape_temp_root(tmp_path):
    with pytest.raises(ValueError, match="workdir"):
        sandbox.run("print(1)", workdir=tmp_path)


def test_syntax_error_reported():
    result = sandbox.run("def broken(:\n  pass")
    assert not result.ok
    assert any("语法错误" in v for v in result.violations)


def test_empty_code_rejected():
    with pytest.raises(ValueError):
        sandbox.run("   ")


def test_workdir_is_temp_and_clean():
    """相对路径写入应落在临时目录，不污染仓库。"""
    before = set(p.name for p in ROOT.iterdir())
    result = sandbox.run("import json; print(json.dumps({'ok': 1}))")
    assert result.ok
    after = set(p.name for p in ROOT.iterdir())
    assert before == after, "沙箱不应在仓库根目录产生文件"
