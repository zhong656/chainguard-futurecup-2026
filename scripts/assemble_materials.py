"""组装「提交材料目录」与「更新后的 D 组交付包」（Owner: B）。

要解决两件事
------------
1. **D 的交付包里 PPT 是未填封面的 v7**。我校对后填好了四项信息（团队/演讲人/指导教师/学校），
   需要把成品换进包里，同时**更新包内的 `文件校验清单.json`** —— 换了文件却不更新清单，
   等于让校验清单说谎。
2. **六项材料散在三四个目录里**，11/19 上传前手工拼一定会漏。这里统一成一个目录，
   命名规范、带 MANIFEST、带一份可勾选的核对表。

命名规范（官方要求"赛题名+队名+项目名"出现在提交件上）
------------------------------------------------------
`ChainGuard_<材料类型>_v<版本>.<ext>`，如 `ChainGuard_方案书_v1.0.pdf`。

用法
----
    python scripts/assemble_materials.py \
        --materials "D:\\未来杯-ChainGuard\\成片材料-20261112" \
        --out "D:\\未来杯-ChainGuard\\提交材料_20261112" \
        --version 1.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
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
import package_submission as ps  # noqa: E402

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_video(path: Path) -> dict:
    """用 ffprobe 读分辨率/时长，用来挑「真 1080p」那份。"""
    exe = shutil.which("ffprobe")
    if not exe:
        return {}
    proc = subprocess.run(
        [exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        return {}
    meta = json.loads(proc.stdout)
    video = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": float(meta.get("format", {}).get("duration") or 0),
    }


def pick_video(materials: Path) -> Path | None:
    """挑分辨率最高的 mp4。

    踩过：微信传输会把 1080p 压成 960×544，文件名还带哈希看不出来。
    所以**按实测分辨率挑，不按文件大小或名字挑**。
    """
    candidates = [p for p in materials.rglob("*.mp4")]
    # 包内的原始视频优先（D 的交付包里有 1080p 原件）
    for zpath in materials.glob("*.zip"):
        try:
            with zipfile.ZipFile(zpath) as zf:
                for name in zf.namelist():
                    if name.endswith(".mp4") and "演示" in name:
                        tmp = materials / "_extracted" / Path(name).name
                        tmp.parent.mkdir(parents=True, exist_ok=True)
                        if not tmp.exists():
                            tmp.write_bytes(zf.read(name))
                        candidates.append(tmp)
        except zipfile.BadZipFile:
            continue

    best, best_h = None, -1
    for path in candidates:
        info = probe_video(path)
        height = info.get("height") or 0
        if height > best_h:
            best, best_h = path, height
    return best


def pick_pptx(materials: Path) -> Path | None:
    """优先含 final/封面 字样的成品，其次最新修改的那份。"""
    files = [p for p in materials.rglob("*.pptx")]
    if not files:
        return None
    finals = [p for p in files if re.search(r"final|封面|filled", p.stem, re.I)]
    pool = finals or files
    return max(pool, key=lambda p: p.stat().st_mtime)


def pick_pdf(materials: Path) -> Path | None:
    files = [p for p in materials.rglob("*.pdf") if "方案书" in p.name or "方案" in p.name]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def rebuild_d_package(materials: Path, pptx: Path, out: Path) -> Path | None:
    """把填好封面的 PPT 换进 D 的交付包，并**重写包内校验清单**。

    踩过：一边往目标 zip 写、一边又打开它读清单 → BadZipFile。
    改为**先把所有条目读进内存**，最后一次性写出（含重算的清单）。
    """
    source = next((p for p in materials.glob("*.zip") if "成果交付包" in p.name
                   and "含封面版" not in p.name), None)
    if source is None:
        print("  [WARN] 找不到 D 的交付包 zip，跳过重建")
        return None

    target = out / f"{source.stem}_含封面版{source.suffix}"
    entries: list[tuple[str, bytes]] = []
    replaced = False

    with zipfile.ZipFile(source) as src:
        for info in src.infolist():
            if info.filename.startswith("文件校验清单"):
                continue
            data = src.read(info.filename)
            if info.filename.endswith(".pptx"):
                data = pptx.read_bytes()
                replaced = True
                print(f"  替换包内 PPT：{info.filename} → {pptx.name}")
            entries.append((info.filename, data))

    if not replaced:
        entries.append((pptx.name, pptx.read_bytes()))

    manifest = [
        {"file": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in entries
    ]
    entries.append(("文件校验清单.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")))

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, data in entries:
            dst.writestr(name, data)

    print(f"  重建交付包：{target.name}（{len(manifest)} 项，清单已重算）")
    return target


def assemble(materials: Path, out: Path, version: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")
    rows: list[tuple[str, Path, str]] = []

    # 1 方案书
    pdf = pick_pdf(materials)
    if pdf:
        dst = out / "01_方案书" / f"ChainGuard_方案书_v{version}.pdf"
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(pdf, dst)
        rows.append(("方案书（官方必交 1）", dst, "≥5000 字 / 8 部分"))

    # 2 PPT
    pptx = pick_pptx(materials)
    if pptx:
        dst = out / "02_方案讲解PPT" / f"ChainGuard_方案讲解PPT_v{version}.pptx"
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(pptx, dst)
        rows.append(("方案讲解 PPT（官方必交 2）", dst, "正文 10~15 页 / 官方模板"))

    # 3 视频
    video = pick_video(materials)
    if video:
        dst = out / "03_演示视频" / f"ChainGuard_演示视频_v{version}.mp4"
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(video, dst)
        info = probe_video(dst)
        rows.append(("演示视频（官方必交 3）", dst,
                     f"{info.get('width')}×{info.get('height')} / {info.get('duration', 0):.0f}s"))

    with tempfile.TemporaryDirectory(prefix="cg-mat-") as tmp:
        work = Path(tmp)
        # 4 源码包
        src_zip = ps._build_source_zip(work)
        dst = out / "04_源码与可运行包" / f"ChainGuard_源码包_v{version}.zip"
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(src_zip, dst)
        rows.append(("源码与可运行包（官方必交 4 的载体）", dst,
                     f"{len(pr.collect_files())} 个文件"))

        # 5 示例输出包
        sample_zip, count = ps._build_sample_zip(work)
        dst = out / "05_示例输出包" / f"ChainGuard_示例输出包_v{version}.zip"
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(sample_zip, dst)
        rows.append(("示例输出包（支撑材料）", dst, f"{count} 项"))

    # 6 文档
    for name, rel in (("作品简介", "docs/作品简介.md"),
                      ("测试报告", "docs/测试报告.md"),
                      ("方案书正文源稿", "docs/方案书-正文.md"),
                      ("官方要求对照", "docs/官方要求-2026.md")):
        path = ROOT / rel
        if path.exists():
            dst = out / "06_文档" / f"{name}.md"
            dst.parent.mkdir(exist_ok=True)
            shutil.copy2(path, dst)
            rows.append((name, dst, "Markdown 源稿"))

    # MANIFEST
    lines = [f"# 提交材料 MANIFEST", f"生成时间: {datetime.now().isoformat(timespec='seconds')}",
             f"仓库提交: {pr._commit_id()}", ""]
    for label, path, note in rows:
        lines.append(f"{sha256(path)}  {path.relative_to(out).as_posix()}  ({path.stat().st_size} B)")
    lines.append("")
    lines.append(f"共 {len(rows)} 项")
    (out / "MANIFEST.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 核对表
    table = ["| # | 材料 | 文件 | 规格 | 状态 |", "| --- | --- | --- | --- | --- |"]
    for i, (label, path, note) in enumerate(rows, 1):
        table.append(f"| {i} | {label} | `{path.relative_to(out).as_posix()}` | {note} | ☑ |")
    checklist = f"""# 提交材料核对表（{stamp}）

> 由 `scripts/assemble_materials.py` 自动生成。改动材料后请重跑，不要手改本表。

{chr(10).join(table)}

## 提交前必须再跑一遍的脚本

```bash
python scripts/check.py                              # 仓库门禁
python scripts/check_video.py "03_演示视频/..."       # 视频 180~300 秒 / ≥1080p
python scripts/check_slides.py "02_方案讲解PPT/..."   # PPT 页数/尺寸/封面四字段/字体
python scripts/check_public_release.py               # 转公开前合规自检
```

## 仍需人工确认

- [ ] PPT 第 5 页大会提示：无国家领导人照片、无国家地图
- [ ] 视频字幕烧录、无 Key/内网地址（已抽帧看过，提交前再看一遍）
- [ ] 仓库已转公开且无 LICENSE / 未开 Pages
"""
    (out / "00_提交清单.md").write_text(checklist, encoding="utf-8")

    print(f"\n[OK] 材料目录：{out}")
    for label, path, note in rows:
        print(f"  ✓ {path.relative_to(out).as_posix():<48} {note}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--materials", type=Path, required=True, help="成片所在目录（仓库外）")
    parser.add_argument("--out", type=Path, required=True, help="生成的提交材料目录")
    parser.add_argument("--version", default="1.0")
    args = parser.parse_args()

    pptx = pick_pptx(args.materials)
    if pptx:
        rebuilt = rebuild_d_package(args.materials, pptx, args.materials)
        if rebuilt:
            print(f"  D 组交付包已更新：{rebuilt.name}\n")

    return assemble(args.materials, args.out, args.version)


if __name__ == "__main__":
    raise SystemExit(main())
