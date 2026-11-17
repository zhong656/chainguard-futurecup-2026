"""提交材料重建器（Owner: B）。

它解决什么
----------
11/19 要用**当时的 main** 重出材料。这件事手工做过一次，踩了四个坑：

1. `build_proposal_pdf.py` 的参数是 `--out`，不是 `--output`；
2. 成片在仓库**外**，只用相对路径会写错地方；
3. 成片目录里有两份视频，散落那份是微信压缩版（544p），**必须按分辨率挑**；
4. **分支内结论不算**——目标提交上没有代码就出材料，等于对外宣称做不到的能力。

三条设计约束（A 在 #94 复审时逐条指出，这里逐条落实）
------------------------------------------------------
1. **查的和建的是同一个提交**：只看 `--ref` 有没有文件不够——实际从工作树构建，
   若工作树 HEAD ≠ ref 指向的提交，产出的材料就与"目标提交"不一致。
   所以构建前强制校验 `git rev-parse HEAD == git rev-parse <ref>`，不等即拒绝。
2. **"只读验证"必须真的只读**：`check.py` 里的纵切会写 `outputs/_vertical`，
   所以默认模式**不运行 check.py**，只做不写盘的检查；要跑门禁请用 `--build`。
3. **视频按分辨率挑，复制后要过门禁**：按体积挑保证不了 1080p（压缩版可能更大）；
   必须用 ffprobe 读高度；选中后还要跑 `check_video.py`，PPT 同理跑 `check_slides.py`。

用法
----
    # 只读预检（不写任何文件、不跑会写盘的检查）
    python scripts/rebuild_materials.py --materials <成片目录> --out <输出目录>

    # 真正重建（会跑 check.py、写 outputs/_vertical、生成 PDF）
    python scripts/rebuild_materials.py --materials <成片目录> --out <输出目录> --build

    # 目标提交尚未包含 L3/MCP 时，显式按旧口径继续（缺失项会写进 summary）
    python scripts/rebuild_materials.py ... --build --allow-missing-l3
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 目标提交上必须存在的两个文件：#91 的核心产物。
# 只查其中一个不够——L3 与 MCP 是两件事，可能分两次合入。
REQUIRED_ON_REF: tuple[str, ...] = (
    "src/cross_check.py",
    "src/mcp/client.py",
)

MIN_HAN = 5000          # 官方：方案书 ≥5000 字
MIN_PAGES = 8
MIN_ARTIFACTS = 9       # 纵切产物件数
MIN_VIDEO_HEIGHT = 1080


class StepError(RuntimeError):
    """某一步失败；调用方据此返回非零退出码。"""


# ── 可测的外部调用（测试里替换掉，避免真跑 git / ffprobe）─────────
def git_output(repo: Path, *args: str) -> str:
    """执行 git 并返回 stdout；失败抛 StepError。"""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise StepError(
            f"git {' '.join(args)} 失败（退出码 {proc.returncode}）："
            f"{(proc.stderr or '').strip()[:200]}"
        )
    return proc.stdout


def resolve_ref_sha(repo: Path, ref: str) -> str:
    return git_output(repo, "rev-parse", f"{ref}^{{commit}}").strip()


def worktree_head(repo: Path) -> str:
    return git_output(repo, "rev-parse", "HEAD").strip()


def git_tracked_files(repo: Path, ref: str) -> set[str]:
    out = git_output(repo, "ls-tree", "-r", "--name-only", ref)
    return {line.strip() for line in out.splitlines() if line.strip()}


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


def probe_height(path: Path) -> int:
    """用 ffprobe 读视频高度；读不到就报错（不能靠体积猜分辨率）。"""
    exe = shutil.which("ffprobe") or "ffprobe"
    proc = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise StepError(f"ffprobe 读取失败：{(proc.stderr or '').strip()[:160]}")
    try:
        return int((proc.stdout or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        raise StepError(f"ffprobe 没有返回高度：{proc.stdout!r}") from None


# ── 纯判定逻辑（易测）──────────────────────────────────────
def missing_on_ref(tracked: set[str], required: tuple[str, ...] = REQUIRED_ON_REF) -> list[str]:
    return [name for name in required if name not in tracked]


def guard_message(missing: list[str]) -> str:
    return (
        f"目标提交上缺少 {', '.join(missing)}——对应能力尚未合入。\n"
        "此时对外口径必须是「L2 两层验证 / MCP 未接入」，不要用分支上的新口径出材料。\n"
        "确认已合入后再跑；确有需要请显式加 --allow-missing-l3。"
    )


def head_mismatch_message(head: str, ref: str, ref_sha: str) -> str:
    return (
        f"工作树 HEAD（{head[:7]}）与 {ref}（{ref_sha[:7]}）不是同一个提交。\n"
        f"继续构建会产出与目标提交不一致的材料。请先切换到该提交：\n"
        f"    git checkout {ref_sha}"
    )


def measure_pdf(path: Path) -> tuple[int, int]:
    """返回 (页数, 汉字数)。"""
    try:
        import pymupdf  # type: ignore
    except ImportError:
        raise StepError("未安装 pymupdf，无法核对汉字数") from None
    doc = pymupdf.open(str(path))
    text = "".join(page.get_text() for page in doc)
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return doc.page_count, han


def pick_video(zip_path: Path, dest_dir: Path,
               min_height: int = MIN_VIDEO_HEIGHT) -> Path:
    """从交付包里挑**分辨率达标**的 mp4（按高度，不按体积）。

    体积靠不住：微信压缩版可能反而更大。挑不到达标项就报错，
    并把每个候选的分辨率列出来，避免"悄悄用了不合格的视频"。
    """
    if not zip_path.exists():
        raise StepError(f"找不到交付包：{zip_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[int, Path]] = []
    with zipfile.ZipFile(zip_path) as zf:
        videos = [n for n in zf.namelist() if n.lower().endswith(".mp4")]
        if not videos:
            raise StepError("交付包里没有 mp4")
        for name in videos:
            zf.extract(name, dest_dir)
            path = dest_dir / name
            candidates.append((probe_height(path), path))
    ok = [(h, p) for h, p in candidates if h >= min_height]
    if not ok:
        listing = "、".join(f"{p.name}={h}p" for h, p in candidates)
        raise StepError(f"交付包里没有 ≥{min_height}p 的视频（候选：{listing}）")
    return max(ok, key=lambda item: item[0])[1]


# ── 主流程 ────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按目标提交重建提交材料（默认只读）")
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--materials", required=True, help="成片材料目录")
    ap.add_argument("--out", required=True, help="输出目录（建议在仓库外）")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--build", action="store_true",
                    help="真正写文件（会跑 check.py，它会写 outputs/_vertical）")
    ap.add_argument("--allow-missing-l3", action="store_true",
                    help="目标提交没有 L3/MCP 也继续（会记入 summary）")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    materials = Path(args.materials).resolve()
    out = Path(args.out).resolve()

    # ── 只读预检：不写任何文件 ──────────────────────────────
    print(f"[1/3] 只读预检：{args.ref} 与工作树")
    try:
        ref_sha = resolve_ref_sha(repo, args.ref)
        head = worktree_head(repo)
        tracked = git_tracked_files(repo, args.ref)
    except StepError as exc:
        print(f"  [FAIL] {exc}")
        return 1

    if head != ref_sha:
        print(f"  [FAIL] {head_mismatch_message(head, args.ref, ref_sha)}")
        return 1
    print(f"  [OK] 工作树即目标提交 {ref_sha[:7]}")

    missing = missing_on_ref(tracked)
    if missing:
        if not args.allow_missing_l3:
            print(f"  [FAIL] {guard_message(missing)}")
            return 1
        print(f"  [WARN] 缺少 {', '.join(missing)}，已显式 --allow-missing-l3，按旧口径继续")
    else:
        print("  [OK] 目标提交已含 L3 与 MCP")

    zip_path = materials / "D组成果交付包_20261112.zip"
    ppt = materials / "路演PPT_v10.pptx"
    for path, label in ((zip_path, "交付包 zip"), (ppt, "PPT")):
        if not path.exists():
            print(f"  [FAIL] 找不到{label}：{path}")
            return 1
    print("  [OK] 成片材料齐（zip + PPT）")

    if not args.build:
        print("\n[只读预检结束] 未写任何文件、未运行会写盘的检查。")
        print("  要真正重建请加 --build（会跑 check.py，它写 outputs/_vertical）")
        return 0

    # ── 构建：从这里开始写文件 ─────────────────────────────
    print(f"[2/3] 仓库门禁：python scripts/check.py（会写 outputs/_vertical）")
    code = run_python(repo, ["scripts/check.py"])
    if code != 0:
        print("  [FAIL] check.py 未通过，停止")
        return code
    print("  [OK] 仓库门禁通过")

    out.mkdir(parents=True, exist_ok=True)

    print(f"[3/3] 重建产物 → {out}")
    code = run_python(repo, ["-m", "src.run", "--output", str(out / "demo")])
    if code != 0:
        print("  [FAIL] 纵切失败")
        return code
    artifacts = [p for p in (out / "demo").rglob("*") if p.is_file()]
    if len(artifacts) < MIN_ARTIFACTS:
        print(f"  [FAIL] 产物不足 {MIN_ARTIFACTS} 件（实际 {len(artifacts)}）")
        return 1
    print(f"  [OK] 产物 {len(artifacts)} 件")

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
    print(f"  · PDF：{pages} 页 / {han} 汉字")
    if pages < MIN_PAGES or han < MIN_HAN:
        print(f"  [FAIL] 不达标（需 ≥{MIN_PAGES} 页、≥{MIN_HAN} 汉字）")
        return 1
    print("  [OK] 方案书达标")

    try:
        video = pick_video(zip_path, out / "_video")
    except StepError as exc:
        print(f"  [FAIL] {exc}")
        return 1
    video_final = out / video.name
    shutil.copy2(video, video_final)
    ppt_final = out / ppt.name
    shutil.copy2(ppt, ppt_final)

    # 复制不是终点：必须过既有的成片门禁
    print("  · 视频门禁")
    if run_python(repo, ["scripts/check_video.py", str(video_final)]) != 0:
        print("  [FAIL] 视频未通过 check_video.py")
        return 1
    print("  · PPT 门禁")
    if run_python(repo, ["scripts/check_slides.py", str(ppt_final)]) != 0:
        print("  [FAIL] PPT 未通过 check_slides.py")
        return 1

    summary = {
        "ref": args.ref,
        "ref_sha": ref_sha,
        "worktree_head": head,
        "repo": str(repo),
        "materials": str(materials),
        "out": str(out),
        "pdf_pages": pages,
        "pdf_han": han,
        "artifacts": len(artifacts),
        "video": video.name,
        "video_height": probe_height(video),
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
