"""公开仓库前的合规自检（Owner: B）。

背景
----
作品提交要求提供"评审可复现的代码仓库地址"，私有库评审打不开，
所以决定**在提交前把仓库转为公开**（2026-11-11 队长决定，方案 A）。

公开是不可逆的（fork 与缓存清不掉），所以公开**之前**必须机器检查一遍，
而不是靠"我觉得没问题"。

检查五项
--------
1. **第三方原文/二进制**：工作树与**全部历史**里都不得有 PDF / Office / 图片；
2. **密钥**：全历史不得出现 `sk-` / `ghp_` / `AKIA` 等模式；
3. **个人信息**：不得出现校名、指导教师、学号等（PPT 封面另按官方要求填写，不入库）；
4. **语料授权字段**：`sources.yaml` 每条必须声明 `third_party_text_included`，且为 false；
5. **LICENSE 缺席**：公开仓库不应携带开源许可证（本作品未授权他人再分发）。

用法：
    python scripts/check_public_release.py
    python scripts/check_public_release.py --skip-history   # 历史扫描很慢，本地快速检查用
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BINARY_SUFFIXES = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
                   ".png", ".jpg", ".jpeg", ".gif", ".zip", ".mp4", ".mov"}
SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"gho_[A-Za-z0-9]{20,}",
    r"AKIA[0-9A-Z]{16}",
)
PERSONAL_PATTERNS = (
    r"指导教师[:：]\s*\S+",
    r"学号[:：]\s*\d{6,}",
)


def _git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=ROOT, check=False,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          encoding="utf-8", errors="replace")
    return proc.stdout if proc.returncode == 0 else ""


def check_tracked_binaries() -> list[str]:
    bad = []
    for line in _git("ls-files").splitlines():
        if Path(line).suffix.lower() in BINARY_SUFFIXES:
            bad.append(line)
    return bad


def check_history_binaries() -> list[str]:
    """历史上删除过的也算——公开后历史同样可见。"""
    out = _git("log", "--all", "--diff-filter=AD", "--name-only", "--pretty=format:")
    seen = {}
    for line in out.splitlines():
        name = line.strip()
        if name and Path(name).suffix.lower() in BINARY_SUFFIXES:
            seen[name] = True
    return sorted(seen)


def check_secrets(use_history: bool) -> list[str]:
    hits = []
    targets = ["."]
    if use_history:
        out = _git("log", "--all", "-p")
    else:
        out = ""
        for path in ROOT.rglob("*"):
            if path.is_file() and ".git" not in path.parts and path.suffix.lower() in {
                ".py", ".md", ".yml", ".yaml", ".json", ".txt", ".env", ".sh"
            }:
                out += path.read_text(encoding="utf-8", errors="replace")
    for pattern in SECRET_PATTERNS:
        for m in re.finditer(pattern, out):
            hits.append(f"{pattern} → {m.group(0)[:12]}…")
    return hits[:5]


def check_personal_info() -> list[str]:
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix.lower() not in {".md", ".py", ".yaml", ".yml", ".json"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            # 说明性文字（"不写""不得""禁止"）不算泄露
            if any(word in line for word in ("不写", "不得", "禁止", "不要", "待补")):
                continue
            for pattern in PERSONAL_PATTERNS:
                if re.search(pattern, line):
                    hits.append(f"{path.relative_to(ROOT)}: {line.strip()[:50]}")
    return hits


def check_corpus_flags() -> list[str]:
    import yaml

    problems = []
    src = yaml.safe_load((ROOT / "knowledge/sources.yaml").read_text(encoding="utf-8"))
    items = src.get("sources") or src.get("documents") or []
    if not items:
        return ["sources.yaml 里没有条目"]
    for it in items:
        sid = it.get("source_id") or it.get("doc_id") or "?"
        flag = it.get("third_party_text_included")
        if flag is None:
            problems.append(f"{sid}: 未声明 third_party_text_included")
        elif flag is not False:
            problems.append(f"{sid}: third_party_text_included={flag}（应为本项目原创转述=false）")
    return problems


def check_license_absent() -> list[str]:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        if (ROOT / name).exists():
            return [f"存在 {name}——本作品未授权他人再分发，公开仓库不应带许可证"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="公开仓库前的合规自检")
    parser.add_argument("--skip-history", action="store_true", help="跳过全历史扫描（较慢）")
    args = parser.parse_args()

    results: list[tuple[str, list[str]]] = []
    results.append(("工作树中的二进制文件", check_tracked_binaries()))
    if not args.skip_history:
        results.append(("历史中出现过的二进制文件", check_history_binaries()))
    results.append(("密钥模式", check_secrets(use_history=not args.skip_history)))
    results.append(("个人信息", check_personal_info()))
    results.append(("语料授权字段", check_corpus_flags()))
    results.append(("LICENSE", check_license_absent()))

    failed = False
    print("公开前自检：")
    for name, problems in results:
        if problems:
            failed = True
            print(f"  [FAIL] {name}（{len(problems)} 项）")
            for p in problems[:6]:
                print(f"         - {p}")
        else:
            print(f"  [OK]   {name}")

    if failed:
        print("\n[FAIL] 存在阻断项，**不要现在转公开**。")
        return 1
    print("\n[PASS] 可以转公开。")
    print("      转公开后本检查失效——仓库已可见，撤回需要 force-push 全部历史，基本不可行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
