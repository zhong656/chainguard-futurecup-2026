"""演示视频核验脚本的判定逻辑测试（Owner: B）。

视频文件本身不进仓库（几十 MB，且赛事要求单个 zip ≤500MB），
所以这里用**伪造的 ffprobe JSON** 测判定逻辑——这比"等真视频来了再试"可靠，
因为判定阈值是明确的数字，不需要真文件也能验证。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_video as cv  # noqa: E402


def _meta(duration=360.0, width=1920, height=1080, vcodec="h264", audio=True):
    streams = [{"codec_type": "video", "width": width, "height": height, "codec_name": vcodec}]
    if audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return {"streams": streams, "format": {"duration": str(duration)}}


def test_good_video_passes():
    problems, facts = cv.evaluate(_meta(), size_bytes=200 * 1024 * 1024)
    assert not problems, problems
    assert any("1080" in f for f in facts)


def test_too_short_rejected():
    problems, _ = cv.evaluate(_meta(duration=120), size_bytes=10**8)
    assert any("时长" in p for p in problems)


def test_too_long_rejected():
    problems, _ = cv.evaluate(_meta(duration=600), size_bytes=10**8)
    assert any("时长" in p for p in problems)


def test_low_resolution_rejected():
    problems, _ = cv.evaluate(_meta(width=1280, height=720), size_bytes=10**8)
    assert any("1080" in p for p in problems)


def test_wrong_codec_rejected():
    problems, _ = cv.evaluate(_meta(vcodec="vp9"), size_bytes=10**8)
    assert any("编码" in p for p in problems)


def test_missing_audio_rejected():
    problems, _ = cv.evaluate(_meta(audio=False), size_bytes=10**8)
    assert any("音轨" in p for p in problems)


def test_oversize_rejected():
    problems, _ = cv.evaluate(_meta(), size_bytes=600 * 1024 * 1024)
    assert any("MB" in p for p in problems)


def test_no_video_stream_rejected():
    problems, _ = cv.evaluate({"streams": [], "format": {"duration": "360"}}, size_bytes=10**8)
    assert problems and "视频流" in problems[0]


def test_hevc_is_allowed():
    """H.265 在部分机器上播放器兼容性差，但技术上可接受——判定要放行。"""
    problems, _ = cv.evaluate(_meta(vcodec="hevc"), size_bytes=10**8)
    assert not problems
