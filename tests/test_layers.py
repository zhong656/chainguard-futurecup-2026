"""三层验证开关的测试（Owner: B）。

`layers` 段以前是注释，代码不读 —— 配置写了等于没写。这份测试锁住三件事：

1. 默认三层开关能被正确读出（L1/L2 开，L3 关）；
2. `llm_judge: false` 时**只跑 L1**，logic 保持 1.0（不臆造分数）；
3. 危险组合**启动即失败**：`rules: false`（失去四个维度的来源）、
   `cross_check: true`（L3 已实现；此前未实现时是拒绝启动，防止"打开后被静默忽略"）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import verifier as vf  # noqa: E402


@pytest.fixture(scope="module")
def draft():
    return {
        "run_id": "run-layers-001",
        "round": 0,
        "sections": [
            {"title": "总体方案", "content": "采用两步走。", "citations": ["kb:a1_gb_t_40659_2021_info"]},
        ],
    }


def test_default_layers_from_config():
    layers = vf._layers()
    assert layers["rules"] is True, "L1 必须默认开启"
    assert layers["llm_judge"] is True, "L2 默认开启"
    # L3 于 2026-11-14 实现并**默认开启**（配置在 configs/verifier.yaml）。
    # 默认开是有意的：它是零成本的确定性复核（纯本地检索，不调模型）。
    assert layers["cross_check"] is True, "L3 已实现，默认开启"


def test_llm_judge_off_returns_l1_only(draft):
    """关掉 L2 时只返回 L1 卡：logic 保持 1.0，且不会出现 L2 的 issue。"""
    v = vf.Verifier(layers={"rules": True, "llm_judge": False, "cross_check": False})
    card = vf.Verifier.verify(v, draft, [{"source_id": "kb:a1_gb_t_40659_2021_info"}])
    assert card["metrics"]["logic"] == 1.0, "没跑 L2 就不该改 logic"
    assert not [i for i in card["issues"] if i["rule_id"].startswith("L2")]


def test_llm_judge_on_merges_l2(draft):
    """开启 L2 时走合并逻辑（用假判定确认它真的被调用）。"""
    v = vf.Verifier(layers={"rules": True, "llm_judge": True, "cross_check": False})
    fake = lambda d, i: (0.5, [])  # noqa: E731
    card = vf.Verifier.verify(v, draft, [{"source_id": "kb:a1_gb_t_40659_2021_info"}], judge_fn=fake)
    assert card["metrics"]["logic"] == 0.5, "L2 的判定必须体现在 logic 维度"


def test_rules_cannot_be_disabled():
    with pytest.raises(vf.VerifierConfigError) as exc:
        vf.Verifier(layers={"rules": False, "llm_judge": True, "cross_check": False})
    assert "rules" in str(exc.value)


def test_cross_check_true_is_accepted_after_l3_implemented():
    """L3 于 2026-11-14 实现（`src/cross_check.py`）。

    旧行为是"配置打开即抛 VerifierConfigError"——那在**未实现**时是对的；
    实现之后必须能开，否则等于把做好的能力锁死。
    """
    v = vf.Verifier(layers={"rules": True, "llm_judge": True, "cross_check": True})
    assert v.layers["cross_check"] is True


def test_cross_check_layer_adds_metric(tmp_path):
    """打开 L3 后评分卡应出现 cross_check 维度（契约允许额外 0~1 数值）。"""
    v = vf.Verifier(layers={"rules": True, "llm_judge": True, "cross_check": True})
    card = v.verify({"run_id": "run-l3", "sections": [
        {"title": "相机选型", "content": "相机选型需要计算分辨率与视野。",
         "citations": ["kb:a3_basler_camera_selection"]},
    ]})
    assert "cross_check" in card["metrics"]


def test_layers_read_from_custom_config(tmp_path):
    cfg = tmp_path / "verifier.yaml"
    cfg.write_text(
        yaml.safe_dump({"layers": {"rules": True, "llm_judge": False, "cross_check": False},
                        "scorecard": {}}),
        encoding="utf-8",
    )
    assert vf._layers(cfg)["llm_judge"] is False


def test_missing_layers_falls_back_to_defaults(tmp_path):
    """配置里没写 layers 时不能当成"全关"，要退回默认值。"""
    cfg = tmp_path / "verifier.yaml"
    cfg.write_text(yaml.safe_dump({"scorecard": {}}), encoding="utf-8")
    assert vf._layers(cfg) == vf.DEFAULT_LAYERS
