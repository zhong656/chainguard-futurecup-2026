"""公开仓库前的合规自检（Owner: B）。

背景
----
作品提交要求提供"评审可复现的代码仓库地址"，私有库评审打不开，
所以决定**在提交前把仓库转为公开**（2026-11-11 队长决定，方案 A）。

公开是不可逆的（fork 与缓存清不掉），所以公开**之前**必须机器检查一遍。

A 在 #84 review 里指出的三处假绿（本版已修）
--------------------------------------------
1. **git 不可用时仍报 [PASS]**：旧版 `_git()` 失败返回空字符串，
   历史扫描"什么都没发现" → 于是判定通过。**"查不到"不等于"没有"。**
   现在：git 扫描失败 → 直接 **FAIL 阻断**（除非显式 `--assume-unverified`，
   且报告里会写清"历史未核验"）。
2. **密钥模式太少**：旧版只有 4 种（sk-/ghp_/gho_/AKIA）。
   现在补 `github_pat_`、`xox[baprs]-`、`AIza`、私钥块、明文 `password=`/`token=` 等。
3. **个人信息模式太窄**：旧版只有"指导教师："与"学号："。
   现在补 学校/学院/导师/姓名等标签，并支持 `--forbid-words` 传入本队真实姓名
   （从仓库外的 `团队信息.md` 读，**不写进仓库**）。

用法：
    python scripts/check_public_release.py
    python scripts/check_public_release.py --skip-history
    python scripts/check_public_release.py --forbid-words "某队名,某姓名"
    python scripts/check_public_release.py --root <待检目录>     # 供 CLI 负例测试用
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

# 例外：`docs/images/` 下是本项目自己界面的截图（方案书需要系统截图）。
ALLOWED_BINARY_PREFIXES = ("docs/images/",)

SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9]{20,}",              # OpenAI 风格
    r"ghp_[A-Za-z0-9]{20,}",             # GitHub PAT（经典）
    r"gho_[A-Za-z0-9]{20,}",             # GitHub OAuth
    r"github_pat_[A-Za-z0-9_]{20,}",     # GitHub PAT（fine-grained）
    r"AKIA[0-9A-Z]{16}",                 # AWS Access Key
    r"xox[baprs]-[A-Za-z0-9-]{10,}",     # Slack
    r"AIza[0-9A-Za-z_\-]{35}",           # Google API key
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"(?i)\b(?:password|passwd|secret|token)\s*[:=]\s*['\"][^'\"]{6,}['\"]",
)

PERSONAL_PATTERNS = (
    r"指导教师\s*[:：]\s*\S+",
    r"(?:指导)?导师\s*[:：]\s*\S+",
    r"学号\s*[:：]\s*\d{4,}",
    r"(?:学校|学院|院系)\s*[:：]\s*\S+",
    r"演讲人\s*[:：]\s*\S+",
    r"团队名称\s*[:：]\s*\S+",
)

TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".json", ".txt", ".cjs", ".js",
                 ".html", ".css", ".cfg", ".ini", ".toml", ".sh", ".ps1", ".svg"}


def _git(*args: str) -> tuple[str, bool]:
    """返回 (输出, 是否成功)。**失败必须能被调用方看见**——这是 #84 的核心修复。"""
    try:
        proc = subprocess.run(["git", *args], cwd=ROOT, check=False,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              encoding="utf-8", errors="replace")
    except OSError:
        return "", False
    return (proc.stdout or "", proc.returncode == 0)


def _read_text(path: Path) -> tuple[str, str | None]:
    """读取文本；读不出来时返回 (\"\", 错误说明)。

    **不可读是阻断项，不是跳过项**（A 在 #84 复审里指出）：
    旧实现 `except ...: continue` 会把"读不了"当成"没问题"，
    一个用了奇怪编码的文件里藏密钥就能整队通过。
    """
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        return "", f"非 UTF-8 编码（{exc.reason}），无法扫描内容"
    except OSError as exc:
        return "", f"读取失败（{type(exc).__name__}），无法扫描内容"


def check_tracked_binaries() -> tuple[list[str], list[str]]:
    """返回 (真实问题, 未核验)。**git 不可用属于"未核验"，不是"无问题"。**"""
    out, ok = _git("ls-files")
    if not ok:
        return [], ["工作树二进制检查：git ls-files 不可用，未能完成"]
    bad = []
    for line in out.splitlines():
        if Path(line).suffix.lower() not in BINARY_SUFFIXES:
            continue
        if line.replace("\\", "/").startswith(ALLOWED_BINARY_PREFIXES):
            continue
        bad.append(line)
    return bad, []


def check_history_binaries() -> tuple[list[str], list[str]]:
    out, ok = _git("log", "--all", "--diff-filter=AD", "--name-only", "--pretty=format:")
    if not ok:
        return [], ["历史二进制检查：git log 不可用，**历史未核验**"]
    seen = {}
    for line in out.splitlines():
        name = line.strip()
        if name and Path(name).suffix.lower() in BINARY_SUFFIXES:
            seen[name] = True
        elif name and Path(name).suffix.lower() in BINARY_SUFFIXES \
                and name.replace("\\", "/").startswith(ALLOWED_BINARY_PREFIXES):
            seen.pop(name, None)
    return sorted(k for k in seen
                  if not k.replace("\\", "/").startswith(ALLOWED_BINARY_PREFIXES)), []


# 规则名：日志里只报"命中了哪条规则"，**绝不复述命中内容**。
# A 在 #84 review 里指出：旧版把「指导教师：某某」整行打进日志，
# 等于为了检查个人信息而先把个人信息写进日志。
SECRET_LABELS = (
    ("sk- 前缀", 0), ("ghp_ 前缀", 1), ("gho_ 前缀", 2), ("github_pat_ 前缀", 3),
    ("AWS Access Key", 4), ("Slack Token", 5), ("Google API Key", 6),
    ("私钥块", 7), ("明文口令赋值", 8),
)
PERSONAL_LABELS = (
    "指导教师标签", "导师标签", "学号标签", "学校/学院标签", "演讲人标签", "团队名称标签",
)


def _scan_secrets(text: str) -> list[str]:
    """只找密钥；返回**规则名**，不含任何命中内容。"""
    hits: list[str] = []
    for label, idx in SECRET_LABELS:
        if re.search(SECRET_PATTERNS[idx], text):
            hits.append(f"命中密钥规则「{label}」")
    return hits


# 占位符写法：值里出现这些词说明还没填，不算真实个人信息
PLACEHOLDER_WORDS = ("按报名", "待填", "待补", "____", "xxx", "某某", "示例", "不写", "不得", "禁止")


def _scan_personal(text: str) -> list[str]:
    """只找个人信息；返回**规则名**，不含命中内容。"""
    hits: list[str] = []
    for idx, label in enumerate(PERSONAL_LABELS):
        for m in re.finditer(PERSONAL_PATTERNS[idx], text):
            line = m.group(0)
            if any(word in line for word in PLACEHOLDER_WORDS):
                continue
            hits.append(f"命中个人信息规则「{label}」")
            break
    return hits


def check_secrets(use_history: bool) -> tuple[list[str], list[str]]:
    hits: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.resolve() == SELF:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text, error = _read_text(path)
        if error is not None:
            hits.append(f"{path.relative_to(ROOT)}: **无法扫描**——{error}（不可豁免）")
            continue
        for hit in _scan_secrets(text):
            hits.append(f"{path.relative_to(ROOT)}: {hit}")

    unverified: list[str] = []
    if use_history:
        out, ok = _git("log", "--all", "-p")
        if not ok:
            unverified.append("历史密钥检查：git log 不可用，**历史未核验**")
        else:
            for label, idx in SECRET_LABELS:
                if re.search(SECRET_PATTERNS[idx], out):
                    hits.append(f"历史中出现密钥规则「{label}」")
    return hits[:10], unverified


# 本脚本自身的路径：它必须写出这些模式串才能做检查，
# 所以扫描时跳过自己，否则每次都会命中自己的文档说明（假阳性）。
SELF = Path(__file__).resolve()


def check_personal_info(extra_words: list[str]) -> tuple[list[str], list[str]]:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.resolve() == SELF:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text, error = _read_text(path)
        if error is not None:
            hits.append(f"{path.relative_to(ROOT)}: **无法扫描**——{error}（不可豁免）")
            continue
        for hit in _scan_personal(text):
            hits.append(f"{path.relative_to(ROOT)}: {hit}")
        for word in extra_words:
            if word and word in text:
                # 允许出现在"禁止/不写"这类说明句里
                for line in text.splitlines():
                    if word in line and not any(w in line for w in ("不写", "不得", "禁止", "不要")):
                        hits.append(f"{path.relative_to(ROOT)}: 出现禁用词（已隐去）")
                        break
    return hits[:10], []


def check_personal_extra_placeholder() -> list[str]:
    return []


def check_corpus_flags() -> tuple[list[str], list[str]]:
    import yaml

    try:
        src = yaml.safe_load((ROOT / "knowledge/sources.yaml").read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [], [f"语料授权检查：sources.yaml 读取失败（{type(exc).__name__}）"]
    items = src.get("sources") or src.get("documents") or []
    if not items:
        return ["sources.yaml 里没有条目"], []   # 空清单是真实问题，不是未核验
    problems = []
    for it in items:
        sid = it.get("source_id") or it.get("doc_id") or "?"
        flag = it.get("third_party_text_included")
        if flag is None:
            problems.append(f"{sid}: 未声明 third_party_text_included")
        elif flag is not False:
            problems.append(f"{sid}: third_party_text_included={flag}（应为原创转述=false）")
    return problems, []


def check_license_absent() -> tuple[list[str], list[str]]:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        if (ROOT / name).exists():
            return [f"存在 {name}——本作品未授权他人再分发，公开仓库不应带许可证"], []
    return [], []


def decide(problems: list[str], unverified: list[str],
           allow_unverified: bool = False) -> tuple[int, str]:
    """判定的唯一入口（纯函数，便于负例测试）。

    规则：
      1. **发现真实问题 → 一律 FAIL**，任何豁免参数都不能把它变成 PASS；
      2. **无法验证 → 默认 FAIL**（A 指出的第二处假绿：跳过历史扫描却报"可以转公开"）；
         只有显式 `allow_unverified` 才放行，且结论里必须写明"未核验"。

    返回 (退出码, 结论文本)。
    """
    real = [p for p in problems if p not in unverified]
    if real:
        return 1, "\n".join([
            "[FAIL] 存在阻断项，**不要现在转公开**：",
            *[f"  - {p}" for p in real[:8]],
        ])

    if unverified:
        if not allow_unverified:
            return 1, "\n".join([
                "[FAIL] 有检查未能完成，**不能判定为可公开**：",
                *[f"  - {p}" for p in unverified[:8]],
                "",
                "  提示：离线环境可加 --assume-unverified 放行，但结论会标注「未核验」；",
                "        真实问题不会因为该参数而被放过。",
            ])
        return 0, "\n".join([
            "[WARN] 已放行，但**历史/部分检查未核验**——不能据此断言仓库干净。",
            *[f"  - {p}" for p in unverified[:8]],
        ])

    return 0, ("[PASS] 可以转公开。\n"
               "      转公开后本检查失效——仓库已可见，撤回需要 force-push 全部历史，基本不可行。")


def main() -> int:
    parser = argparse.ArgumentParser(description="公开仓库前的合规自检")
    parser.add_argument("--skip-history", action="store_true",
                        help="跳过全历史扫描（会显著降低保证强度，报告中标注）")
    parser.add_argument("--assume-unverified", action="store_true",
                        help="有检查未完成时仍放行（仅限离线环境；结论会标注「未核验」，"
                             "真实问题不会被放过）")
    parser.add_argument("--forbid-words", default="",
                        help="本队真实姓名/队名，逗号分隔；从仓库外文件读取后传入")
    parser.add_argument("--root", default="",
                        help="待检查的目录（缺省为仓库根）。CLI 负例测试用，"
                             "便于对临时目录跑同一套门禁")
    args = parser.parse_args()

    global ROOT
    if args.root:
        ROOT = Path(args.root).resolve()

    extra = [w.strip() for w in args.forbid_words.replace("，", ",").split(",") if w.strip()]

    results: list[tuple[str, list[str], list[str]]] = []

    def add(name: str, pair: tuple[list[str], list[str]]) -> None:
        found, missing = pair
        results.append((name, found, missing))

    add("工作树中的二进制文件", check_tracked_binaries())
    if not args.skip_history:
        add("历史中出现过的二进制文件", check_history_binaries())
    add("密钥与个人信息（工作树）", check_secrets(use_history=False))
    add("个人信息（含禁用词）", check_personal_info(extra))
    add("语料授权字段", check_corpus_flags())
    add("LICENSE", check_license_absent())
    if not args.skip_history:
        # 只保留历史部分的命中，避免与工作树扫描重复报同一条
        found, missing = check_secrets(use_history=True)
        add("密钥（全历史）", ([h for h in found if h.startswith("历史")], missing))

    problems: list[str] = []
    unverified: list[str] = []
    print("公开前自检：")
    for name, found, missing in results:
        if found:
            problems.extend(f"{name}：{x}" for x in found)
            print(f"  [FAIL] {name}（{len(found)} 项）")
            for x in found[:6]:
                print(f"         - {x}")
        elif missing:
            unverified.extend(f"{name}：{x}" for x in missing)
            print(f"  [SKIP] {name}（未能完成，**不算通过**）")
            for x in missing[:6]:
                print(f"         - {x}")
        else:
            print(f"  [OK]   {name}")

    if args.skip_history:
        unverified.append("已按 --skip-history 跳过全历史扫描：**历史未核验**")

    code, message = decide(problems, unverified, args.assume_unverified)
    print()
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
