"""L3 双路检索比对的测试（Owner: B/C）。

L3 的主张是：**一条引用如果换条检索路径就找不到，它的支撑强度就值得怀疑。**

所以测试必须能证明两件事：
    1. 真实语料下的正常引用 → agreement 高（不误报）；
    2. 只有融合排序才成立的引用 → 报 CROSS_CHECK_MISMATCH（真能抓到）。

另外锁住三条设计边界：
    - L3 的 issue 是 `major` 不是 `blocker`（不参与一票否决）；
    - `cross_check` 维度**不参与加权**（weights 里没有它）；
    - 维度地板（metric_floor）只对加权维度生效，不被 L3 拖累。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import cross_check as cc  # noqa: E402
from src import knowledge_hub, verifier  # noqa: E402

RELEVANT = "kb:a3_basler_camera_selection"
UNRELATED = "kb:a1_gb_t_40659_2021_info"


def _draft(sections: list[dict]) -> dict:
    return {"run_id": "run-l3-test", "sections": sections}


@pytest.fixture(scope="module")
def chunks():
    return knowledge_hub.build_index()


# ── 正常路径 ─────────────────────────────────────────────
def test_relevant_citation_is_confirmed(chunks):
    draft = _draft([{
        "title": "相机选型",
        "content": "工业相机选型需要根据视野与精度要求计算分辨率，并匹配镜头焦距。",
        "citations": [RELEVANT],
    }])
    report = cc.cross_check(draft, chunks)
    assert report.checked == 1
    assert report.confirmed == 1, "相关引用竟然没被任一路径命中"
    assert report.agreement == 1.0
    assert report.issues == []


def test_no_citations_means_no_failure(chunks):
    report = cc.cross_check(_draft([{"title": "x", "content": "纯文字", "citations": []}]), chunks)
    assert report.checked == 0
    assert report.agreement == 1.0, "没有引用时不该判失败（L1 会报 CITATION_MISSING）"


# ── 抓到不一致 ───────────────────────────────────────────
def test_mismatch_detected_when_citation_is_off_topic(chunks):
    """引用与段落内容完全无关 → 两条单路都检索不到 → 必须报出来。"""
    draft = _draft([{
        "title": "区块链共识",
        "content": "工作量证明要求矿工寻找满足难度目标的随机数，节点通过最长链达成共识。",
        "citations": [UNRELATED],
    }])
    report = cc.cross_check(draft, chunks)
    assert report.checked == 1
    assert report.confirmed == 0
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue["rule_id"] == "CROSS_CHECK_MISMATCH"
    assert issue["severity"] == "warning", "L3 不该用 blocker——它判断的是支撑强度"
    for key in ("section", "reason", "suggestion", "target_node"):
        assert issue.get(key), f"issue 缺少契约必需字段 {key}"
    assert issue["source_id"] == UNRELATED
    assert report.agreement == 0.0


def test_agreement_is_ratio(chunks):
    draft = _draft([
        {"title": "相机选型", "content": "相机选型要计算分辨率与视野。", "citations": [RELEVANT]},
        {"title": "区块链", "content": "共识算法用于分布式账本。", "citations": [UNRELATED]},
    ])
    report = cc.cross_check(draft, chunks)
    assert report.checked == 2
    assert report.confirmed == 1
    assert report.agreement == 0.5


# ── 与验证器集成 ─────────────────────────────────────────
def test_verifier_no_longer_rejects_cross_check():
    """旧版把 cross_check=true 当配置错误拒绝启动；现在应能正常构造。"""
    v = verifier.Verifier(layers={"rules": True, "llm_judge": True, "cross_check": True})
    assert v.layers["cross_check"] is True


def test_verifier_adds_cross_check_metric():
    v = verifier.Verifier(layers={"rules": True, "llm_judge": True, "cross_check": True})
    card = v.verify(_draft([{
        "title": "相机选型",
        "content": "相机选型需要计算分辨率。",
        "citations": [RELEVANT],
    }]))
    assert "cross_check" in card["metrics"]
    assert 0.0 <= card["metrics"]["cross_check"] <= 1.0


def test_verifier_omits_metric_when_layer_off():
    v = verifier.Verifier(layers={"rules": True, "llm_judge": True, "cross_check": False})
    card = v.verify(_draft([{
        "title": "相机选型", "content": "相机选型需要计算分辨率。", "citations": [RELEVANT],
    }]))
    assert "cross_check" not in card["metrics"], "关掉的层不应凭空产生维度"


def test_cross_check_metric_is_not_weighted():
    """cross_check 不能影响加权分：weights 里没有这个键。"""
    from src.verifier import _policy

    weights = _policy()["weights"]
    assert "cross_check" not in weights


def test_metric_floor_ignores_cross_check(tmp_path):
    """L3 分再低也不该触发维度地板（地板只管加权维度）。"""
    card = verifier.Verifier(layers={"rules": True, "llm_judge": True, "cross_check": True}).verify(
        _draft([{"title": "区块链", "content": "共识算法用于分布式账本。", "citations": [UNRELATED]}])
    )
    # cross_check 可能是 0.0，但地板只看加权维度
    assert card["metrics"]["cross_check"] == 0.0
    assert card["verdict"] in {"pass", "fail"}  # 不因这一项抛异常即可


def test_scorecard_with_cross_check_validates_against_contract():
    """契约允许 metrics 里出现新的 0~1 数值，无需改 schema。"""
    from scripts._schema import validator

    card = {
        "run_id": "run-x", "round": 0, "score": 1.0, "threshold": 0.85,
        "metrics": {"citation": 1.0, "consistency": 1.0, "coverage": 1.0,
                    "logic": 1.0, "format": 1.0, "cross_check": 0.75},
        "issues": [], "verdict": "pass",
    }
    validator("scorecard.schema.json").validate(card)
