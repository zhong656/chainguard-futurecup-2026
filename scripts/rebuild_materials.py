"""提交材料重建器（Owner: B）。

它解决什么
----------
11/19 要用**当时的 main** 重出材料。这件事手工做过一次，踩了四个坑：

1. `build_proposal_pdf.py` 的参数是 `--out`，不是 `--output`；
2. 成片在仓库**外**（`D:\\未来杯-ChainGuard\\...`），只用相对路径会写错地方；
3. 成片目录里有两份视频，散落那份是微信压缩版（544p），**必须用 zip 内 1080p 版**；
4. **分支内结论不算**——main 上还没有代码就出材料，等于对外宣称做不到的能力。

所以把这些判断固化成一个可复核、可测试的脚本，而不是靠人记。

核心是一条硬门禁
----------------
默认先确认 `origin/main` 里**真的有** `src/cross_check.py` 与 `src/mcp/client.py`；
没有就退出 1，并提示"此时对外口径只能是 L2 / MCP 未接入"。
**宁可不出材料，也不出与代码不一致的材料。**

用法
----
    # 只验证，不写任何文件（默认）
    python scripts/rebuild_materials.py --repo . --materials <成片目录> --out <输出目录>

    # 真正重建
    python scripts/rebuild_materials.py ... --build

    # 明明没合入却要出"旧口径"材料时，显式关闭该门禁（会被记录在输出里）
    python scripts/rebuild_materials.py ... --build --allow-missing-l3

参数
----
`--repo`      仓库路径（默认脚本所在仓库）
`--materials` 成片材料目录（含 PDF / PPT / 交付包 zip）
`--out`       输出目录（建议在仓库外，避免污染工作树）
`--ref`       用于判定"已合入"的引用（默认 `origin/main`）
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# main 上必须存在的两个文件：#91 的核心产物。
# 只查其中一个不够——L3 与 MCP 是两件事，可能分两次合入。
REQUIRED_ON_MAIN: tuple[str, ...] = (
    "src/cross_check.py",
    "src/mcp/client.py",
)

MIN_HAN = 5000          # 官方：方案书 ≥5000 字
MIN_PAGES = 8
MIN_ARTIFACTS = 9       # 纵切产物件数


class StepError(RuntimeError):
    """某一步失败；调用方据此返回非零退出码。"""


# ── 可测的外部调用（测试里替换掉，避免真跑 git / 真联网）──────────
def git_tracked_files(repo: Path, ref: str) -> set[str]:
    """列出某个 ref 上被跟踪的文件（失败抛 StepError）。"""
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", ref],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise StepError(
            f"无法读取 {ref} 的文件列表（git 退出码 {proc.returncode}）；"
            "可能还没 fetch，或该 ref 不存在"
        )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def run_python(repo: Path, args: list[str]) -> int:
    """以当前解释器运行仓库内脚本，返回退出码。"""
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    for line in (proc.stdout or "").splitlines()[-6:]:
        print(f"    {line}")
    for line in (proc.stderr or "").splitlines()[-3:]:
        print(f"    ! {line}")
    return proc.returncode


# ── 纯判定逻辑（易测）──────────────────────────────────────
def missing_on_ref(tracked: set[str], required: tuple[str, ...] = REQUIRED_ON_MAIN) -> list[str]:
    """返回 required 里在 tracked 中缺失的项。"""
    return [name for name in required if name not in tracked]


def guard_message(missing: list[str]) -> str:
    return (
        f"目标分支上缺少 {', '.join(missing)}——对应能力尚未合入。\n"
        "此时对外口径必须是「L2 两层验证 / MCP 未接入」，不要用分支上的新口径出材料。\n"
        "确认已合入后再跑；确有需要请显式加 --allow-missing-l3。"
    )


def measure_pdf(path: Path) -> tuple[int, int]:
    """返回 (页数, 汉字数)。优先用 pymupdf，装不上时退化为只数字节。"""
    try:
        import pymupdf  # type: ignore
    except ImportError:  # pragma: no cover - 环境相关
        raise StepError("未安装 pymupdf，无法核对汉字数") from None
    doc = pymupdf.open(str(path))
    text = "".join(page.get_text() for page in doc)
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return doc.page_count, han


def pick_video(zip_path: Path, dest_dir: Path) -> Path:
    """从交付包 zip 里取出体积最大的 mp4（避开微信压缩版）。"""
    if not zip_path.exists():
        raise StepError(f"找不到交付包：{zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        videos = [n for n in zf.namelist() if n.lower().endswith(".mp4")]
        if not videos:
            raise StepError("交付包里没有 mp4")
        name = max(videos, key=lambda n: zf.getinfo(n).file_size)
        dest_dir.mkdir(parents=True, exist_ok=True)
        zf.extract(name, dest_dir)
        return dest_dir / name


# ── 主流程 ────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按 main 重建提交材料（默认只验证）")
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--materials", required=True, help="成片材料目录")
    ap.add_argument("--out", required=True, help="输出目录（建议在仓库外）")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--build", action="store_true", help="真正写文件")
    ap.add_argument("--allow-missing-l3", action="store_true",
                    help="即使目标 ref 上没有 L3/MCP 也继续（会被明确记录）")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    materials = Path(args.materials).resolve()
    out = Path(args.out).resolve()

    print(f"[1/5] 检查 {args.ref} 是否已含 L3 与 MCP")
    try:
        tracked = git_tracked_files(repo, args.ref)
    except StepError as exc:
        print(f"  [FAIL] {exc}")
        return 1
    missing = missing_on_ref(tracked)
    if missing:
        if not args.allow_missing_l3:
            print(f"  [FAIL] {guard_message(missing)}")
            return 1
        print(f"  [WARN] 缺少 {', '.join(missing)}，但已显式 --allow-missing-l3，按旧口径继续")
    else:
        print("  [OK] 已含 src/cross_check.py 与 src/mcp/client.py")

    print(f"[2/5] 仓库门禁：python scripts/check.py（在 {repo.name}）")
    code = run_python(repo, ["scripts/check.py"])
    if code != 0:
        print("  [FAIL] check.py 未通过，停止")
        return code
    print("  [OK] 仓库门禁通过")

    if not args.build:
        print("\n[验证模式] 未写任何文件；要重建请加 --build")
        return 0

    out.mkdir(parents=True, exist_ok=True)

    print(f"[3/5] 重跑纵切 → {out / 'demo'}")
    code = run_python(repo, ["-m", "src.run", "--output", str(out / "demo")])
    if code != 0:
        print("  [FAIL] 纵切失败")
        return code
    artifacts = [p for p in (out / "demo").rglob("*") if p.is_file()]
    if len(artifacts) < MIN_ARTIFACTS:
        print(f"  [FAIL] 产物不足 {MIN_ARTIFACTS} 件（实际 {len(artifacts)}）")
        return 1
    print(f"  [OK] 产物 {len(artifacts)} 件")

    print("[4/5] 重建方案书 PDF")
    pdf = out / "方案书_链衡ChainGuard_v2.pdf"
    code = run_python(repo, ["scripts/build_proposal_pdf.py", "--out", str(pdf)])
    if code != 0 or not pdf.exists():
        print("  [FAIL] PDF 未生成（Windows 上需要本机安装 Word）")
        return 1
    try:
        pages, han = measure_pdf(pdf)
    except StepError as exc:
        print(f"  [FAIL] {exc}")
        return 1
    print(f"  · {pages} 页 / {han} 汉字")
    if pages < MIN_PAGES or han < MIN_HAN:
        print(f"  [FAIL] 不达标（需 ≥{MIN_PAGES} 页、≥{MIN_HAN} 汉字）")
        return 1
    print("  [OK] 方案书达标")

    print("[5/5] 取 1080p 视频并复制 PPT")
    zip_path = materials / "D组成果交付包_20261112.zip"
    try:
        video = pick_video(zip_path, out / "_video")
    except StepError as exc:
        print(f"  [FAIL] {exc}")
        return 1
    print(f"  · 视频：{video.name}")
    shutil.copy2(video, out / "演示视频_v2.mp4")
    ppt = materials / "路演PPT_v10.pptx"
    if not ppt.exists():
        print(f"  [FAIL] 找不到 PPT：{ppt}")
        return 1
    shutil.copy2(ppt, out / ppt.name)

    summary = {
        "ref": args.ref,
        "repo": str(repo),
        "materials": str(materials),
        "out": str(out),
        "pdf_pages": pages,
        "pdf_han": han,
        "artifacts": len(artifacts),
        "video": video.name,
        "allowed_missing": missing,
    }
    (out / "rebuild-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[完成] {out}")
    print("  下一步：把汉字数回填 docs/提交材料清单.md（开 PR 走 A 审）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
