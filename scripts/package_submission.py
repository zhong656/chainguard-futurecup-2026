"""组装最终提交包（Owner: B，材料 5/最终上传）。

为什么需要它
------------
评审只允许**一次上传**、单包 ≤500MB、名字是 `赛题名+队名+项目名`。
手拼的问题不是费力，是**会漏**——漏一项就得重新上传。

所以这个脚本在打包**之前**先核对清单：六项材料缺哪项就直说，并拒绝出包。
宁可本地报错，也不要在上传页面才发现少了项目文档。

用法：
    python scripts/package_submission.py --team "队名" --materials "D:\\成片材料-20261110"
    python scripts/package_submission.py --team "队名" --materials ... --allow-missing  # 预演

`--materials` 指向仓库外的目录，里面放视频 / PPT / PDF 成片（这些不进仓库）。
文件名要能认出来：见下面的 `MATERIAL_PATTERNS`。
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import package_release as pr  # noqa: E402

DIST = ROOT / "dist"
MAX_MB = 500

# 成片目录的**文件名契约**：按名字认，不按后缀猜。
#
# 教训：第一版按后缀找文件，把 D 的 PPT 导出 PDF（chainguard-d-materials-v5.pdf）
# 当成了"项目文档"，于是脚本报"六项齐全"——而项目文档其实还没排版。
# **假绿比缺项更危险**：缺项会让人去找，假绿会让人放心。
MATERIAL_PATTERNS: dict[str, tuple[set[str], tuple[str, ...]]] = {
    "演示视频": ({".mp4", ".mov"}, ("演示视频", "demo", "video")),
    "路演PPT": ({".pptx"}, ("路演", "ppt", "slides")),
    "项目文档PDF": ({".pdf"}, ("项目文档", "白皮书")),
}

REQUIRED_DOCS = {
    "作品简介": "docs/作品简介.md",
    "测试报告": "docs/测试报告.md",
    "项目文档正文": "docs/项目文档-正文.md",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_source_zip(workdir: Path) -> Path:
    """复用 package_release 的白名单与打包逻辑。"""
    files = pr.collect_files()
    target = workdir / "源码包.zip"
    pr.build_zip(files, target)
    return target


def _build_sample_zip(workdir: Path) -> tuple[Path, int]:
    """跑一次纵切，把产物打成示例输出包（9 件产物 + 包内 README）。"""
    from src.vertical_slice import run_vertical_slice

    out = workdir / "_sample"
    run_vertical_slice("用机器视觉升级精密零件产线质检", output=out)

    (out / "README.md").write_text(
        "# 示例输出包\n\n"
        "由 `python -m src.run` 生成的交付物样本。\n"
        "`evidence_refs.json` 给出每条引用的 文件 / 页码 / 字符区间 / 原文 / 哈希，可回原文核对。\n"
        "页码仅 PDF/DOCX 等分页格式才有值；当前语料为 Markdown，`page` 为 null。\n",
        encoding="utf-8",
    )

    target = workdir / "示例输出包.zip"
    count = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=f"示例输出包/{path.relative_to(out).as_posix()}")
                count += 1
    return target, count


def _collect_docs() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name, rel in REQUIRED_DOCS.items():
        path = ROOT / rel
        if path.exists():
            out[name] = path
    return out


def _find_materials(materials: Path) -> tuple[dict[str, Path], list[Path]]:
    """按文件名契约识别成片；返回 (已识别, 未识别文件列表)。

    未识别不算错误，但会**列出来**——让打包的人确认是不是改个名就能被认出来。
    """
    found: dict[str, Path] = {}
    unknown: list[Path] = []
    if not materials.exists():
        return found, unknown
    for path in sorted(materials.rglob("*")):
        if not path.is_file():
            continue
        matched = False
        for key, (suffixes, keywords) in MATERIAL_PATTERNS.items():
            if key in found or path.suffix.lower() not in suffixes:
                continue
            if any(k in path.stem.lower() for k in keywords):
                found[key] = path
                matched = True
                break
        if not matched:
            unknown.append(path)
    return found, unknown


def main() -> int:
    parser = argparse.ArgumentParser(description="组装最终提交包")
    parser.add_argument("--team", required=True, help="队名，用于包名：赛题一_<队名>_链衡ChainGuard")
    parser.add_argument("--materials", type=Path, required=True, help="仓库外的成片目录")
    parser.add_argument("--allow-missing", action="store_true", help="缺项也出包（仅预演用）")
    args = parser.parse_args()

    docs = _collect_docs()
    mats, unknown = _find_materials(args.materials)

    required = ("作品简介", "测试报告", "项目文档PDF", "演示视频")
    missing = [name for name in required if name not in docs and name not in mats]

    print("材料核对：")
    for name, path in {**docs, **mats}.items():
        print(f"  ✓ {name:<10} {path.name}")
    for name in missing:
        print(f"  ✗ {name:<10} 缺失（在 --materials 目录放一个文件名含「{name[:4]}」的文件）")
    if unknown:
        print("  未识别（名字对不上契约，可能是成品也可能不是）：")
        for path in unknown:
            print(f"    ? {path.name}")

    if missing and not args.allow_missing:
        print(f"\n[FAIL] 缺 {len(missing)} 项材料，拒绝出包（预演请加 --allow-missing）：{missing}")
        return 1

    stamp = datetime.now().strftime("%Y%m%d")
    prefix = f"赛题一_{args.team}_链衡ChainGuard"
    DIST.mkdir(parents=True, exist_ok=True)
    target = DIST / f"{prefix}_{stamp}.zip"

    with tempfile.TemporaryDirectory(prefix="cg-submission-") as tmp:
        work = Path(tmp)
        print("\n构建子包……")
        source_zip = _build_source_zip(work)
        print(f"  源码包       {source_zip.stat().st_size / 1024:.0f} KB（{len(pr.collect_files())} 个文件）")
        sample_zip, sample_count = _build_sample_zip(work)
        print(f"  示例输出包   {sample_zip.stat().st_size / 1024:.0f} KB（{sample_count} 项）")

        entries: list[tuple[Path, str]] = [
            (source_zip, "源码与可运行包.zip"),
            (sample_zip, "示例输出包.zip"),
        ]
        for name, path in docs.items():
            entries.append((path, f"{name}.md"))
        for name, path in mats.items():
            entries.append((path, f"{name}{path.suffix}"))

        manifest = [
            f"package: {prefix}",
            f"built_at: {datetime.now().isoformat(timespec='seconds')}",
            f"repo_commit: {pr._commit_id()}",
            f"files: {len(entries)}",
            "",
            "# 逐文件 sha256（与包内路径一致）",
        ]
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as zf:
            for path, arcname in entries:
                zf.write(path, arcname=arcname)
                manifest.append(f"{_sha256(path)}  {arcname}  ({path.stat().st_size} B)")
            if missing:
                manifest += ["", "# 缺失项（--allow-missing 预演打包，不可上传）"]
                manifest += [f"MISSING: {m}" for m in missing]
            zf.writestr("MANIFEST.txt", "\n".join(manifest) + "\n")

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"\n[OK] 提交包 → {target.relative_to(ROOT)}（{size_mb:.1f} MB，{len(entries)} 项）")
    if size_mb > MAX_MB:
        print(f"[FAIL] 超过 {MAX_MB} MB 单包上限")
        return 1
    if missing:
        print(f"[WARN] 这是预演包，缺：{missing}——**不可上传**")
        return 0
    print("[PASS] 六项材料齐全，可上传")
    print("       上传后**必须下载回来再核一遍**：解压能跑、视频能播、PDF 能开。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
