"""打包脚本在「无 .git 快照」下的降级行为（Owner: B）。

C 在 19e4b32 的干净 zip 快照上实测发现：`git status --porcelain` 返回 128，
脚本直接崩。**评审拿到的是解压包，不是 git 仓库**——这条必须能用。

本文件锁三件事：
    1. `_git()` 在 git 不可用或非仓库时返回 default，不抛异常；
    2. `_commit_id()` 优先读 `GIT_COMMIT`（容器/无 .git 场景的注入方式）；
    3. 白名单打包数 == 仓库登记文件数（口径一致，材料里不会出现两个数字）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import package_release as pr  # noqa: E402


def test_git_returns_default_when_missing(monkeypatch):
    """git 不存在（OSError）时返回 default，而不是抛出。"""

    def boom(*args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr(pr.subprocess, "run", boom)
    assert pr._git("rev-parse", "HEAD", default="unknown") == "unknown"


def test_git_returns_default_on_nonzero_exit(monkeypatch):
    """非 git 仓库时 git 退出码 128 —— 必须降级，不能崩。"""

    class Fake:
        returncode = 128
        stdout = ""
        stderr = "fatal: not a git repository"

    monkeypatch.setattr(pr.subprocess, "run", lambda *a, **k: Fake())
    assert pr._git("status", "--porcelain", default="") == ""


def test_commit_id_prefers_env(monkeypatch):
    """容器/快照场景用 GIT_COMMIT 注入提交号。"""
    monkeypatch.setenv("GIT_COMMIT", "deadbee")
    assert pr._commit_id() == "deadbee"


def test_commit_id_falls_back_to_unknown(monkeypatch):
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setattr(pr, "_git", lambda *a, **k: k.get("default", ""))
    assert pr._commit_id() == "unknown"


def _tracked_files() -> set[str] | None:
    """取仓库登记文件；**在解压包里（无 .git）返回 None**，调用方跳过。

    这个跳过是必需的：源码包内没有 .git，`git ls-files` 必然失败；
    若硬跑会让"解压后 check.py 通过"这条验收直接挂掉。
    """
    # `-c core.quotepath=false` 是必需的：GitHub Actions 默认转义非 ASCII 路径
    # （输出成 "docs/\345\210\260..."），与本机行为不同，会让比对整体失配。
    proc = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files"], cwd=pr.ROOT, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        return None
    return set((proc.stdout or "").splitlines())


def test_packaged_count_matches_tracked():
    """打包白名单应与仓库登记文件一致——避免材料里出现「177 vs 172」两个数。"""
    tracked = _tracked_files()
    if tracked is None:
        pytest.skip("不在 git 仓库内（源码包解压场景），跳过口径比对")
    packed = {p.relative_to(pr.ROOT).as_posix() for p in pr.collect_files()}
    missing = sorted(tracked - packed)
    assert not missing, (
        "这些仓库文件没进打包白名单：" + ", ".join(missing)
        + "（新增一级目录后要同步 INCLUDE_DIRS）"
    )


def test_ci_config_is_packaged():
    """.github/ 必须进包：CI 门禁是工程纪律的证据，且不含密钥。"""
    packed = {p.relative_to(pr.ROOT).as_posix() for p in pr.collect_files()}
    assert ".github/workflows/ci.yml" in packed, "源码包应包含 CI 配置"
