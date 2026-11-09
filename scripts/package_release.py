"""打源码包并验证它真的能跑（Owner: B，材料 #4）。

为什么不能只 `zip -r`
--------------------
"可运行包"的要求是**评审解压后能直接跑**。只打包不验证，最常见的翻车方式：
漏了 `knowledge/sources.yaml`、带上了本地 `outputs/`、或者把 `.git` 打进去导致
`commit_sha` 读成本机状态。

所以本脚本做三件事：

1. **白名单打包**：只收源码/配置/文档/测试，排除生成物与本机状态；
2. **写清单**：`MANIFEST.txt` 记录提交号、打包时间、逐文件 sha256；
3. **解压验证**（默认开）：把包解到临时目录，在那里跑一遍 `scripts/check.py`。
   **这一步失败就不产出交付包**——宁可报错，也不交付一个跑不起来的 zip。

用法：
    python scripts/package_release.py                 # 打包 + 验证
    python scripts/package_release.py --skip-verify   # 只打包（不建议）
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"

# 只收这些顶层目录/文件：白名单比黑名单安全（新增文件不会意外漏收或被误收）
INCLUDE_DIRS = ("src", "scripts", "tests", "cases", "contracts", "configs",
                "workflows", "agents", "knowledge", "web", "docs")
INCLUDE_FILES = ("README.md", "requirements.txt", "Dockerfile", "docker-compose.yml",
                 ".dockerignore", ".gitignore", "Makefile", "SECURITY.md", "CONTRIBUTING.md")

# 无论在哪都要排除的东西：生成物、本机状态、可再生的缓存
EXCLUDE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".log"}
EXCLUDE_RELATIVE = {
    "docs/consistency-report.md",      # 生成物（CI 有专门守卫）
    "knowledge/source_index.json",     # 生成物
    "dist",                            # 自身
}
# 语料原件（第三方 PDF）不随包分发，见 docs/语料来源与合规.md
EXCLUDE_UNDER = "knowledge/corpus"
EXCLUDE_UNDER_SUFFIXES = {".pdf"}

SIZE_LIMIT_MB = 500  # 赛事规定：单个压缩包 ≤ 500MB，且只有一次上传机会


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=True,
        encoding="utf-8", errors="replace",
    )
    return proc.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_files() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.exists():
            files.append(p)
    for dirname in INCLUDE_DIRS:
        base = ROOT / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() in EXCLUDE_SUFFIXES:
                continue
            if rel in EXCLUDE_RELATIVE:
                continue
            if rel.startswith(EXCLUDE_UNDER + "/") and path.suffix.lower() in EXCLUDE_UNDER_SUFFIXES:
                continue
            files.append(path)
    return files


def build_zip(files: list[Path], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            zf.write(path, arcname=path.relative_to(ROOT).as_posix())
        manifest = [
            f"commit: {_git('rev-parse', 'HEAD')}",
            f"branch: {_git('rev-parse', '--abbrev-ref', 'HEAD')}",
            f"packed_at: {datetime.now(timezone.utc).isoformat()}",
            f"files: {len(files)}",
            "",
            "# 逐文件 sha256（与包内路径一致）",
            *[f"{_sha256(p)}  {p.relative_to(ROOT).as_posix()}" for p in files],
        ]
        zf.writestr("MANIFEST.txt", "\n".join(manifest) + "\n")
    return target


def verify(target: Path) -> tuple[bool, str]:
    """解压到临时目录并在那里跑 check.py —— 这才是"可运行"的定义。"""
    with tempfile.TemporaryDirectory(prefix="cg-release-") as tmp:
        with zipfile.ZipFile(target) as zf:
            zf.extractall(tmp)
        # Windows 上 text=True 会按 GBK 解码，脚本输出是 UTF-8 → 必须显式指定
        proc = subprocess.run(
            [sys.executable, "scripts/check.py"],
            cwd=tmp, capture_output=True, check=False,
            encoding="utf-8", errors="replace",
        )
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-6:])
        return proc.returncode == 0, tail


def main() -> int:
    parser = argparse.ArgumentParser(description="打可运行源码包")
    parser.add_argument("--skip-verify", action="store_true", help="跳过解压验证（不建议）")
    parser.add_argument("--name", default="", help="包名前缀，缺省用 赛题一_链衡ChainGuard")
    args = parser.parse_args()

    dirty = _git("status", "--porcelain")
    if dirty:
        print("[WARN] 工作区有未提交改动，打包内容可能不是某个确定的提交：")
        for line in dirty.splitlines()[:5]:
            print("   ", line)

    files = collect_files()
    stamp = datetime.now().strftime("%Y%m%d")
    prefix = args.name or "赛题一_链衡ChainGuard"
    target = DIST / f"{prefix}_{stamp}.zip"
    build_zip(files, target)

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"[OK] 打包 {len(files)} 个文件 → {target.relative_to(ROOT)}（{size_mb:.1f} MB）")
    if size_mb > SIZE_LIMIT_MB:
        print(f"[FAIL] 超过赛事 500MB 单包上限：{size_mb:.1f} MB")
        return 1

    if args.skip_verify:
        print("[WARN] 已跳过解压验证——交付前必须补跑一次")
        return 0

    ok, tail = verify(target)
    print("[OK] 解压后 check.py 通过" if ok else "[FAIL] 解压后 check.py 未通过")
    print(tail)
    if not ok:
        target.unlink(missing_ok=True)
        print("已删除不合格的包：宁可不出包，也不交付跑不起来的 zip")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
