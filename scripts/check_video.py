"""演示视频参数核验（Owner: B，材料 #3）。

机器能判的
----------
时长、分辨率、编码、音轨、文件大小——这些用 ffprobe 读元数据即可，不靠人眼。

机器判不了的（必须人眼看）
--------------------------
- 字幕是否烧录进画面；
- 画面里有没有 API Key / 内网地址 / 他人姓名；
- 四幕是否齐全（真实运行 / DAG 流转 / fail→pass 评分卡 / Trace 重放）。

所以本脚本跑完给的是"参数合格"，**不是"视频合格"**。最后一步永远是人看一遍。

用法：
    python scripts/check_video.py demo/ChainGuard演示.mp4
    python scripts/check_video.py demo/xxx.mp4 --frames 4    # 顺手抽 4 帧便于目视
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

MIN_SECONDS = 300   # 5 分钟
MAX_SECONDS = 480   # 8 分钟
MIN_HEIGHT = 1080   # 1080p
MAX_MB = 500        # 赛事单包上限
ALLOWED_CODECS = {"h264", "hevc"}


def _ffprobe(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise SystemExit(
            "[FAIL] 找不到 ffprobe。安装 FFmpeg 后重试：\n"
            "       winget install Gyan.FFmpeg   或   https://ffmpeg.org/download.html"
        )
    proc = subprocess.run(
        [exe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"[FAIL] ffprobe 读取失败：{(proc.stderr or '').strip()[:200]}")
    return json.loads(proc.stdout)


def evaluate(meta: dict, size_bytes: int) -> tuple[list[str], list[str]]:
    """返回 (问题列表, 事实列表)。纯函数，便于测试。"""
    problems: list[str] = []
    facts: list[str] = []

    streams = meta.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        problems.append("没有视频流")
        return problems, facts

    duration = float(meta.get("format", {}).get("duration") or 0)
    height = int(video.get("height") or 0)
    width = int(video.get("width") or 0)
    codec = str(video.get("codec_name") or "").lower()
    size_mb = size_bytes / 1024 / 1024

    facts.append(f"时长 {duration:.0f}s（{duration/60:.1f} 分钟）")
    facts.append(f"分辨率 {width}×{height}")
    facts.append(f"编码 {codec}")
    facts.append(f"音轨 {'有' if audio else '无'}")
    facts.append(f"文件 {size_mb:.1f} MB")

    if not (MIN_SECONDS <= duration <= MAX_SECONDS):
        problems.append(
            f"时长 {duration:.0f}s 不在 {MIN_SECONDS}–{MAX_SECONDS}s（5–8 分钟）范围内"
        )
    if height < MIN_HEIGHT:
        problems.append(f"高度 {height} 低于 {MIN_HEIGHT}p")
    if codec not in ALLOWED_CODECS:
        problems.append(f"编码 {codec or '未知'} 不在 {sorted(ALLOWED_CODECS)} 内")
    if audio is None:
        problems.append("没有音轨——演示视频应当有讲解")
    if size_mb > MAX_MB:
        problems.append(f"文件 {size_mb:.1f} MB 超过 {MAX_MB} MB 单包上限")

    return problems, facts


def extract_frames(path: Path, count: int, outdir: Path) -> list[Path]:
    """均匀抽帧，便于人眼核对字幕与敏感信息。"""
    exe = shutil.which("ffmpeg")
    if not exe:
        return []
    exe_probe = shutil.which("ffprobe")
    meta = json.loads(subprocess.run(
        [exe_probe, "-v", "error", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    ).stdout)
    duration = float(meta.get("format", {}).get("duration") or 0)
    outdir.mkdir(parents=True, exist_ok=True)
    outs: list[Path] = []
    for i in range(count):
        ts = duration * (i + 1) / (count + 1)
        out = outdir / f"frame_{i + 1}_{ts:.0f}s.jpg"
        subprocess.run(
            [exe, "-v", "error", "-y", "-ss", f"{ts:.1f}", "-i", str(path), "-frames:v", "1", str(out)],
            capture_output=True, check=False,
        )
        if out.exists():
            outs.append(out)
    return outs


def main() -> int:
    parser = argparse.ArgumentParser(description="演示视频参数核验")
    parser.add_argument("path", type=Path)
    parser.add_argument("--frames", type=int, default=0, help="抽取 N 帧到同目录 frames/")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"[FAIL] 文件不存在：{args.path}")
        return 1

    meta = _ffprobe(args.path)
    problems, facts = evaluate(meta, args.path.stat().st_size)

    print(f"文件：{args.path.name}")
    for fact in facts:
        print(f"  · {fact}")

    if args.frames:
        frames = extract_frames(args.path, args.frames, args.path.parent / "frames")
        if frames:
            print(f"  已抽 {len(frames)} 帧到 {frames[0].parent}")

    if problems:
        print("\n[FAIL] 参数不合格：")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\n[PASS] 参数合格（时长/分辨率/编码/音轨/体积）")
    print("       仍需人眼看一遍：字幕是否烧录、有无 Key/内网地址、四幕是否齐全")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
