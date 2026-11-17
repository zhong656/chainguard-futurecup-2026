"""`scripts/rebuild_materials.py` 的测试（Owner: B）。

这个脚本的核心价值是**一条硬门禁**：
目标 ref 上没有 L3/MCP 的代码时，拒绝用新口径出材料。

所以测试的重点不是"能不能跑完"，而是：
    1. 缺代码时必须退出 1，且提示口径；
    2. 显式 `--allow-missing-l3` 时才放行，且记录下来；
    3. 路径全部来自参数，不依赖硬编码的机器路径；
    4. 视频必须取 zip 内最大的那个（避开微信压缩版）；
    5. 验证模式**不写任何文件**。
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import rebuild_materials as rb  # noqa: E402


# ── 纯逻辑 ───────────────────────────────────────────────
def test_missing_on_ref_detects_each_required_file():
    assert rb.missing_on_ref(set()) == list(rb.REQUIRED_ON_MAIN)
    have = {"src/cross_check.py"}
    assert rb.missing_on_ref(have) == ["src/mcp/client.py"]


def test_guard_message_mentions_fallback_wording():
    """拒绝时的提示必须点明降级口径，否则看日志的人不知道该写什么。"""
    msg = rb.guard_message(["src/cross_check.py"])
    assert "src/cross_check.py" in msg
    assert "L2" in msg and "MCP" in msg
    assert "--allow-missing-l3" in msg


# ── 门禁行为（替换掉 git 与子进程，保持离线可测）────────────
@pytest.fixture()
def no_files(tmp_path):
    """所有路径都在 tmp 下，不碰真实仓库。"""
    return {
        "repo": tmp_path / "repo",
        "materials": tmp_path / "materials",
        "out": tmp_path / "out",
    }


def _args(paths, *extra):
    return [
        "--repo", str(paths["repo"]),
        "--materials", str(paths["materials"]),
        "--out", str(paths["out"]),
        *extra,
    ]


def test_refuses_when_l3_missing(monkeypatch, no_files, capsys):
    monkeypatch.setattr(rb, "git_tracked_files", lambda repo, ref: {"README.md"})
    monkeypatch.setattr(rb, "run_python", lambda repo, args: pytest.fail("不该跑 check"))

    code = rb.main(_args(no_files))
    out = capsys.readouterr().out
    assert code == 1
    assert "尚未合入" in out or "缺少" in out


def test_allow_missing_flag_proceeds(monkeypatch, no_files, capsys):
    monkeypatch.setattr(rb, "git_tracked_files", lambda repo, ref: {"README.md"})
    monkeypatch.setattr(rb, "run_python", lambda repo, args: 0)

    code = rb.main(_args(no_files, "--allow-missing-l3"))
    out = capsys.readouterr().out
    assert code == 0
    assert "[WARN]" in out


def test_verify_mode_writes_nothing(monkeypatch, no_files, capsys):
    tracked = {"src/cross_check.py", "src/mcp/client.py"}
    monkeypatch.setattr(rb, "git_tracked_files", lambda repo, ref: tracked)
    monkeypatch.setattr(rb, "run_python", lambda repo, args: 0)

    code = rb.main(_args(no_files))
    assert code == 0
    assert not no_files["out"].exists(), "验证模式不该创建输出目录"


def test_check_failure_stops(monkeypatch, no_files):
    tracked = {"src/cross_check.py", "src/mcp/client.py"}
    monkeypatch.setattr(rb, "git_tracked_files", lambda repo, ref: tracked)
    monkeypatch.setattr(rb, "run_python", lambda repo, args: 3)

    assert rb.main(_args(no_files, "--build")) == 3


def test_git_failure_is_reported_not_crash(monkeypatch, no_files, capsys):
    def boom(repo, ref):
        raise rb.StepError("无法读取 origin/main")

    monkeypatch.setattr(rb, "git_tracked_files", boom)
    code = rb.main(_args(no_files))
    assert code == 1
    assert "无法读取" in capsys.readouterr().out


# ── 路径参数化 ────────────────────────────────────────────
def test_paths_come_from_arguments(monkeypatch, tmp_path, capsys):
    """仓库/成片/输出三处路径都必须来自参数，不能有硬编码。"""
    repo = tmp_path / "myrepo"
    materials = tmp_path / "mats"
    out = tmp_path / "dest"
    repo.mkdir()
    materials.mkdir()

    monkeypatch.setattr(rb, "git_tracked_files",
                        lambda r, ref: {"src/cross_check.py", "src/mcp/client.py"})
    seen = {}

    def fake_run(r, args):
        seen["repo"] = r
        return 0

    monkeypatch.setattr(rb, "run_python", fake_run)
    code = rb.main(["--repo", str(repo), "--materials", str(materials), "--out", str(out)])
    assert code == 0
    assert Path(seen["repo"]) == repo


# ── 视频挑选 ─────────────────────────────────────────────
def test_pick_video_prefers_largest(tmp_path):
    """zip 里若有多个 mp4，取体积最大的（压缩版通常更小）。"""
    zpath = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("演示视频_v2.mp4", b"x" * 5000)     # 1080p 版
        zf.writestr("微信压缩版.mp4", b"x" * 100)       # 544p 版
    picked = rb.pick_video(zpath, tmp_path / "v")
    assert picked.name == "演示视频_v2.mp4"


def test_pick_video_errors_when_zip_missing(tmp_path):
    with pytest.raises(rb.StepError):
        rb.pick_video(tmp_path / "nope.zip", tmp_path / "v")


def test_pick_video_errors_when_no_mp4(tmp_path):
    zpath = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("readme.txt", "x")
    with pytest.raises(rb.StepError):
        rb.pick_video(zpath, tmp_path / "v")


# ── 记录 ────────────────────────────────────────────────
def test_summary_records_allowed_missing(monkeypatch, no_files, tmp_path):
    """显式放行时必须把"缺了什么"写进 summary，不能悄悄放过。"""
    monkeypatch.setattr(rb, "git_tracked_files", lambda r, ref: set())
    monkeypatch.setattr(rb, "run_python", lambda r, args: 0)
    monkeypatch.setattr(rb, "measure_pdf", lambda p: (10, 6000))

    def fake_pick(zip_path, dest):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "演示视频_v2.mp4"
        f.write_bytes(b"x")
        return f

    monkeypatch.setattr(rb, "pick_video", fake_pick)

    out = no_files["out"]
    demo = out / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    for i in range(rb.MIN_ARTIFACTS):
        (demo / f"f{i}.txt").write_text("x", encoding="utf-8")

    def fake_run_py(repo, args):
        if "--out" in args:                      # build_proposal_pdf
            Path(args[args.index("--out") + 1]).write_bytes(b"%PDF-1.4")
        return 0

    monkeypatch.setattr(rb, "run_python", fake_run_py)
    no_files["materials"].mkdir(parents=True, exist_ok=True)
    (no_files["materials"] / "路演PPT_v10.pptx").write_bytes(b"x")

    code = rb.main(_args(no_files, "--build", "--allow-missing-l3"))
    assert code == 0
    summary = json.loads((out / "rebuild-summary.json").read_text(encoding="utf-8"))
    assert summary["allowed_missing"], "显式放行时 summary 必须记录缺失项"
