"""`scripts/rebuild_materials.py` 的测试（Owner: B）。

三条设计约束各对应一组测试（A 在 #94 复审时逐条指出）：

1. **查的和建的是同一个提交**：工作树 HEAD ≠ 目标 ref 时必须拒绝；
2. **"只读验证"必须真的只读**：默认模式不跑 `check.py`（它会写 outputs/_vertical）；
3. **视频按分辨率挑且复制后过门禁**：体积靠不住；复制后要跑 check_video / check_slides。
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

SHA_A = "a" * 40
SHA_B = "b" * 40


@pytest.fixture()
def paths(tmp_path):
    repo = tmp_path / "repo"
    materials = tmp_path / "materials"
    out = tmp_path / "out"
    repo.mkdir()
    materials.mkdir()
    (materials / "D组成果交付包_20261112.zip").write_bytes(b"PK")
    (materials / "路演PPT_v10.pptx").write_bytes(b"PK")
    return {"repo": repo, "materials": materials, "out": out}


def _args(p, *extra):
    return [
        "--repo", str(p["repo"]),
        "--materials", str(p["materials"]),
        "--out", str(p["out"]),
        *extra,
    ]


def _stub_git(monkeypatch, *, head=SHA_A, ref_sha=SHA_A, tracked=None):
    tracked = {"src/cross_check.py", "src/mcp/client.py"} if tracked is None else tracked
    monkeypatch.setattr(rb, "resolve_ref_sha", lambda repo, ref: ref_sha)
    monkeypatch.setattr(rb, "worktree_head", lambda repo: head)
    monkeypatch.setattr(rb, "git_tracked_files", lambda repo, ref: tracked)


# ── 约束 1：查的提交 == 建的提交 ───────────────────────────
def test_head_mismatch_refused(monkeypatch, paths, capsys):
    _stub_git(monkeypatch, head=SHA_A, ref_sha=SHA_B)
    monkeypatch.setattr(rb, "run_python", lambda repo, args: pytest.fail("不该往下跑"))

    code = rb.main(_args(paths))
    out = capsys.readouterr().out
    assert code == 1
    assert "不是同一个提交" in out
    assert "git checkout" in out


def test_head_mismatch_message_names_both_commits():
    msg = rb.head_mismatch_message(SHA_A, "origin/main", SHA_B)
    assert SHA_A[:7] in msg and SHA_B[:7] in msg


def test_same_head_proceeds(monkeypatch, paths, capsys):
    _stub_git(monkeypatch)
    code = rb.main(_args(paths))
    assert code == 0
    assert "目标提交" in capsys.readouterr().out


# ── 约束 2：默认模式真的只读 ─────────────────────────────
def test_default_mode_does_not_run_check(monkeypatch, paths, capsys):
    """默认模式不得运行 check.py（它会写 outputs/_vertical）。"""
    _stub_git(monkeypatch)
    monkeypatch.setattr(rb, "run_python", lambda repo, args: pytest.fail("只读模式不该跑任何子脚本"))

    code = rb.main(_args(paths))
    out = capsys.readouterr().out
    assert code == 0
    assert "只读预检结束" in out
    assert not paths["out"].exists(), "只读模式不得创建输出目录"


# ── 门禁：目标提交缺文件 ─────────────────────────────────
def test_refuses_when_l3_missing(monkeypatch, paths, capsys):
    _stub_git(monkeypatch, tracked={"README.md"})
    code = rb.main(_args(paths))
    out = capsys.readouterr().out
    assert code == 1
    assert "L2" in out and "MCP" in out


def test_allow_missing_flag_proceeds(monkeypatch, paths, capsys):
    _stub_git(monkeypatch, tracked={"README.md"})
    assert rb.main(_args(paths, "--allow-missing-l3")) == 0
    assert "[WARN]" in capsys.readouterr().out


def test_missing_on_ref_lists_each_file():
    assert rb.missing_on_ref(set()) == list(rb.REQUIRED_ON_REF)
    assert rb.missing_on_ref({"src/cross_check.py"}) == ["src/mcp/client.py"]


def test_git_failure_reported(monkeypatch, paths, capsys):
    def boom(repo, ref):
        raise rb.StepError("无法读取 origin/main")

    monkeypatch.setattr(rb, "resolve_ref_sha", boom)
    assert rb.main(_args(paths)) == 1
    assert "无法读取" in capsys.readouterr().out


# ── 约束 3：视频按分辨率挑 ───────────────────────────────
def test_pick_video_uses_height_not_size(tmp_path, monkeypatch):
    """压缩版可能更大：体积大 ≠ 分辨率高。必须按 ffprobe 高度挑。"""
    zpath = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("压缩版.mp4", b"x" * 9000)     # 体积大，但只有 544p
        zf.writestr("原版.mp4", b"x" * 1000)       # 体积小，但 1080p

    heights = {"压缩版.mp4": 544, "原版.mp4": 1080}
    monkeypatch.setattr(rb, "probe_height", lambda p: heights[p.name])

    picked = rb.pick_video(zpath, tmp_path / "v")
    assert picked.name == "原版.mp4"


def test_pick_video_rejects_when_none_reach_1080(tmp_path, monkeypatch):
    zpath = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("a.mp4", b"x")
    monkeypatch.setattr(rb, "probe_height", lambda p: 544)

    with pytest.raises(rb.StepError) as exc:
        rb.pick_video(zpath, tmp_path / "v")
    assert "544p" in str(exc.value), "报错应列出候选分辨率，便于排查"


def test_pick_video_missing_zip(tmp_path):
    with pytest.raises(rb.StepError):
        rb.pick_video(tmp_path / "nope.zip", tmp_path / "v")


def test_probe_height_errors_are_wrapped(monkeypatch):
    class R:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(rb.subprocess, "run", lambda *a, **k: R())
    with pytest.raises(rb.StepError):
        rb.probe_height(Path("x.mp4"))


# ── 构建路径：复制后必须过门禁 ───────────────────────────
def _prepare_build(monkeypatch, paths):
    _stub_git(monkeypatch)
    calls: list[list[str]] = []

    def fake_run(repo, args):
        calls.append(list(args))
        if args and args[0] == "scripts/build_proposal_pdf.py":
            Path(args[args.index("--out") + 1]).write_bytes(b"%PDF-1.4")
        return 0

    monkeypatch.setattr(rb, "run_python", fake_run)
    monkeypatch.setattr(rb, "measure_pdf", lambda p: (18, 6000))
    monkeypatch.setattr(rb, "probe_height", lambda p: 1080)

    def fake_pick(zip_path, dest):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / "演示视频_v2.mp4"
        f.write_bytes(b"x")
        return f

    monkeypatch.setattr(rb, "pick_video", fake_pick)
    return calls


def _make_demo(paths):
    demo = paths["out"] / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    for i in range(rb.MIN_ARTIFACTS):
        (demo / f"f{i}.txt").write_text("x", encoding="utf-8")


def test_build_runs_video_and_slide_gates(monkeypatch, paths):
    calls = _prepare_build(monkeypatch, paths)
    _make_demo(paths)

    code = rb.main(_args(paths, "--build"))
    assert code == 0
    joined = [" ".join(c) for c in calls]
    assert any("check_video.py" in c for c in joined), "复制后必须跑视频门禁"
    assert any("check_slides.py" in c for c in joined), "复制后必须跑 PPT 门禁"


def test_build_fails_when_video_gate_fails(monkeypatch, paths, capsys):
    _prepare_build(monkeypatch, paths)
    _make_demo(paths)

    def failing(repo, args):
        if args and args[0] == "scripts/check_video.py":
            return 1
        if args and args[0] == "scripts/build_proposal_pdf.py":
            Path(args[args.index("--out") + 1]).write_bytes(b"%PDF-1.4")
        return 0

    monkeypatch.setattr(rb, "run_python", failing)
    assert rb.main(_args(paths, "--build")) == 1
    assert "视频未通过" in capsys.readouterr().out


def test_summary_records_ref_and_missing(monkeypatch, paths):
    _prepare_build(monkeypatch, paths)
    _stub_git(monkeypatch, tracked=set())
    _make_demo(paths)

    code = rb.main(_args(paths, "--build", "--allow-missing-l3"))
    assert code == 0
    summary = json.loads((paths["out"] / "rebuild-summary.json").read_text(encoding="utf-8"))
    assert summary["ref_sha"] == SHA_A
    assert summary["worktree_head"] == SHA_A
    assert summary["allowed_missing"], "显式放行时必须记录缺失项"
    assert summary["video_height"] >= 1080
