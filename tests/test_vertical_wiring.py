"""接线验证（Owner: A 的文件、B 补的测试）。

证明两件事，而不是"看代码觉得接上了"：
    1. `rounds.json` 真的记录了每轮评分卡，且进了 manifest
    2. L2 Verifier 真的在链路里 —— 把它的判定注入后，输出必须出现 L2 的 issue
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import vertical_slice  # noqa: E402


@pytest.fixture(scope="module")
def run_with_output(tmp_path_factory):
    out = tmp_path_factory.mktemp("vertical")
    result = vertical_slice.run_vertical_slice("用机器视觉升级精密零件产线质检", output=out)
    return out, result


def test_rounds_json_records_fail_to_pass(run_with_output):
    """首轮必须不合格、终轮必须通过——这是考察点 5 的物证。"""
    out, result = run_with_output
    rounds = json.loads((out / "rounds.json").read_text(encoding="utf-8"))
    assert len(rounds) >= 2, "至少两轮，否则演示看不到 fail→pass"
    assert rounds[0]["verdict"] == "fail", "首轮应不合格（Mock 故意漏一条引用）"
    assert rounds[-1]["verdict"] == "pass", "终轮应通过"
    assert rounds[0]["issues"], "首轮必须带问题项，否则失败不可解释"


def test_rounds_json_in_manifest(run_with_output):
    """图表/轮次这类附录必须进 manifest，否则'可核验'只覆盖正文。"""
    out, _ = run_with_output
    artifact = json.loads((out / "delivery_artifact.json").read_text(encoding="utf-8"))
    paths = [f["path"] for f in artifact["manifest"]["files"]]
    assert "rounds.json" in paths
    assert "solution.md" in paths and "trace.jsonl" in paths


def test_l2_verifier_is_actually_wired(monkeypatch):
    """把 L2 的判定换成已知值，输出里必须出现它——证明链路真的经过 L2。

    这里用 warning 而不是 blocker：blocker 会让每轮都失败、最终 abort，
    就测不到"通过时带着 L2 意见"这个更常见的情况。
    """
    import src.verifier as verifier_mod

    def fake_judge(draft, index):
        return 0.7, [
            {
                "section": "2. 技术选型",
                "reason": "L2：该段与前文假设不一致",
                "suggestion": "统一口径后重写",
                "target_node": "write",
                "rule_id": "L2_CONTRADICTION",
                "severity": "warning",
            }
        ]

    monkeypatch.setattr(verifier_mod, "_mock_judge", fake_judge)
    result = vertical_slice.run_vertical_slice("机器视觉", output=None)

    seen = {i.get("rule_id") for r in result["rounds"] for i in r["issues"]}
    assert "L2_CONTRADICTION" in seen, "L2 的 issue 没有出现在 rounds 里，说明 verify 节点没走 L2"
    # L2 压低了 logic，最终分不应还是满分
    assert result["scorecard"]["metrics"]["logic"] < 1.0


def test_commit_sha_falls_back_to_env(monkeypatch):
    """容器/zip 里没有 .git，必须能从 GIT_COMMIT 拿到，而不是抛异常。"""
    monkeypatch.setenv("GIT_COMMIT", "deadbee")
    assert vertical_slice._commit_sha() == "deadbee"

def test_charts_are_rendered_and_in_manifest(run_with_output):
    """图表必须进 manifest —— 否则"可核验"只覆盖文本，图可以随便改。"""
    out, _ = run_with_output
    artifact = json.loads((out / "delivery_artifact.json").read_text(encoding="utf-8"))
    paths = [f["path"] for f in artifact["manifest"]["files"]]
    assert "charts/scorecard.svg" in paths
    assert "charts/convergence.svg" in paths
    for name in ("scorecard.svg", "convergence.svg"):
        svg = (out / "charts" / name).read_text(encoding="utf-8")
        assert svg.startswith("<svg"), f"{name} 不是合法 SVG"