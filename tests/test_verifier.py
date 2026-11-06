"""C：L2 独立验证器测试。

覆盖四组：
    1) 独立性：verifier / writer 温度必须不同，verifier 必须只读
    2) 规则：结论无引用 / 结论与证据不搭 / 跨章节数字打架，好稿不误伤
    3) 合并：schema 合规、按配置重算、一票否决、judge_fn 注入、确定性
    4) 对接：输出直连 D 的 LoopController，回退点落在真实节点内
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from scripts._schema import validator  # noqa: E402
from src.dag_compiler import compile_workflow  # noqa: E402
from src.loop_controller import LoopController  # noqa: E402
from src.rule_checker import check as l1_check  # noqa: E402
from src.verifier import (  # noqa: E402
    L2Judgement,
    Verifier,
    VerifierConfigError,
    default_verifier,
    judge,
    verify,
)

EVIDENCE = {
    "mv:doc001": (
        "精密零件产线依赖人工复检，机器视觉质检升级按阶段推进，"
        "回收期以复检人力与客诉赔付两项计算，论点与证据保持一致。"
    ),
    "mv:doc002": "机器视觉改造按单线 6 周推进，质检环节需要可追溯的判定依据。",
}
REQUIRED_SECTIONS = (
    "现状痛点",
    "技术选型",
    "数据方案",
    "实施阶段",
    "成本与ROI",
    "风险与合规",
)


def _sec(title: str, content: str, citations=None) -> dict:
    section = {"title": title, "content": content}
    if citations is not None:
        section["citations"] = citations
    return section


def _draft(sections: list[dict], round_: int = 0) -> dict:
    return {"run_id": "run-l2-001", "round": round_, "sections": sections}


def _good_draft() -> dict:
    return _draft(
        [
            _sec(
                "现状痛点",
                "当前质检环节依赖人工复检，漏检率与过杀率同时偏高，缺乏可追溯依据。",
                ["mv:doc001"],
            ),
            _sec(
                "技术选型",
                "因此建议采用机器视觉质检方案，按单线 6 周推进。",
                ["mv:doc002"],
            ),
        ]
    )


def _full_draft() -> dict:
    """六章齐全、引用可回溯、无结论标记：L1 本来会判 pass。"""
    return _draft(
        [
            _sec(
                name,
                "本方案围绕精密零件产线的机器视觉质检升级展开，论点与证据保持一致。",
                ["mv:doc001"],
            )
            for name in REQUIRED_SECTIONS
        ]
    )


def _contradiction_draft() -> dict:
    return _draft(
        [
            _sec("实施阶段", "改造周期为 6 周，逐线推进。", ["mv:doc001"]),
            _sec("成本与ROI", "因此改造周期为 12 周，回收期顺延。", ["mv:doc001"]),
        ]
    )


def _policy() -> dict:
    return yaml.safe_load((ROOT / "configs" / "verifier.yaml").read_text(encoding="utf-8"))[
        "scorecard"
    ]


# ---------------- 1) 独立性 ---------------- #


def test_default_config_is_independent():
    v = Verifier()
    assert v.verifier_temperature == 0.0
    assert v.writer_temperature == 0.3
    assert v.verifier_spec["read_only"] is True
    assert v.verifier_spec["tier"] == "strong"
    assert default_verifier() is default_verifier()


def test_rejects_same_temperature():
    with pytest.raises(VerifierConfigError, match="同源"):
        Verifier(
            verifier_spec={"temperature": 0.3, "read_only": True},
            writer_spec={"temperature": 0.3},
        )


def test_rejects_writable_verifier():
    with pytest.raises(VerifierConfigError, match="read_only"):
        Verifier(
            verifier_spec={"temperature": 0.0, "read_only": False},
            writer_spec={"temperature": 0.3},
        )


def test_rejects_missing_temperature():
    with pytest.raises(VerifierConfigError, match="temperature"):
        Verifier(verifier_spec={"read_only": True}, writer_spec={"temperature": 0.3})


# ---------------- 2) 规则 ---------------- #


def test_good_draft_keeps_logic_full():
    result = judge(_good_draft(), EVIDENCE)
    assert isinstance(result, L2Judgement)
    assert result.logic == 1.0
    assert result.issues == ()


def test_unsupported_conclusion_is_penalised():
    draft = _draft([_sec("现状痛点", "因此建议立刻更换全部质检设备。")])
    result = judge(draft, {})
    assert result.logic == 0.7
    assert [i["rule_id"] for i in result.issues] == ["LOGIC_UNSUPPORTED"]
    assert result.issues[0]["target_node"] == "write"
    assert result.issues[0]["severity"] == "warning"


def test_contradiction_across_sections_is_penalised():
    result = judge(_contradiction_draft(), EVIDENCE)
    ids = [i["rule_id"] for i in result.issues]
    assert "LOGIC_CONTRADICTION" in ids
    issue = next(i for i in result.issues if i["rule_id"] == "LOGIC_CONTRADICTION")
    assert issue["target_node"] == "fanout"
    assert result.logic == 0.7


def test_conclusion_unrelated_to_evidence_is_penalised():
    draft = _draft(
        [_sec("技术选型", "因此建议引入机器视觉质检方案。", ["mv:doc001"])]
    )
    evidence = {
        "mv:doc001": "本文件记录财务报表审计流程与年度差旅报销标准，与产线设备选型无关事项说明。"
    }
    result = judge(draft, evidence)
    assert [i["rule_id"] for i in result.issues] == ["LOGIC_JUMP"]
    assert result.logic == 0.75


def test_short_evidence_skips_jump_check():
    """证据链只有 id、或语料过短时不能把「没原文」误判成逻辑不通。"""
    draft = _draft([_sec("技术选型", "因此建议引入机器视觉质检方案。", ["mv:doc001"])])
    assert judge(draft, {"mv:doc001": "略"}).issues == ()
    assert judge(draft, ["mv:doc001"]).issues == ()


# ---------------- 3) 合并 ---------------- #


def test_full_good_draft_passes_without_l2_penalty():
    card = verify(_full_draft(), EVIDENCE)
    validator("scorecard.schema.json").validate(card)
    assert card["metrics"]["logic"] == 1.0
    assert card["verdict"] == "pass"
    assert card["score"] == 1.0


def test_l1_always_gives_logic_one():
    """对照：L1 的 logic 恒 1.0，L2 才是真正填这一维的地方。"""
    assert l1_check(_good_draft(), EVIDENCE)["metrics"]["logic"] == 1.0


def test_veto_triggered_by_low_logic():
    """加权分再高，logic 低于 0.60 也要一票否决。"""
    assert verify(_full_draft(), EVIDENCE)["verdict"] == "pass"

    def low_judge(draft, index):
        return 0.5, []

    card = verify(_full_draft(), EVIDENCE, judge_fn=low_judge)
    assert card["metrics"]["logic"] == 0.5
    assert min(card["metrics"].values()) < _policy()["veto"]["metric_floor"]
    # logic 权重 0.20：0.5 只让加权分从 1.0 掉到 0.90，分数本来够，
    # 仍必须判 fail —— 这才验证了一票否决独立于加权分。
    assert card["score"] >= _policy()["pass_threshold"]
    assert card["verdict"] == "fail"


def test_judge_fn_is_injectable():
    def custom(draft, index):
        return 0.42, []

    assert judge(_good_draft(), EVIDENCE, judge_fn=custom).logic == 0.42
    assert verify(_full_draft(), EVIDENCE, judge_fn=custom)["metrics"]["logic"] == 0.42


def test_score_is_recomputed_with_configured_weights():
    def custom(draft, index):
        return 0.5, []

    card = verify(_full_draft(), EVIDENCE, judge_fn=custom)
    weights = _policy()["weights"]
    expected = round(
        sum(weights[k] * card["metrics"][k] for k in weights), 3
    )
    assert card["score"] == expected
    assert card["threshold"] == _policy()["pass_threshold"]


def test_round_is_preserved():
    draft = _draft(
        [_sec("现状痛点", "当前质检依赖人工复检。", ["mv:doc001"])], round_=2
    )
    card = verify(draft, EVIDENCE)
    assert card["round"] == 2


def test_deterministic():
    a = verify(_full_draft(), EVIDENCE)
    b = verify(_full_draft(), EVIDENCE)
    assert a == b


def test_evidence_forms_do_not_crash():
    for evidence in (
        EVIDENCE,
        None,
        [{"source_id": "mv:doc001", "text": EVIDENCE["mv:doc001"]}],
        {"items": [{"source_id": "mv:doc001", "text": EVIDENCE["mv:doc001"]}]},
    ):
        card = verify(_good_draft(), evidence)
        validator("scorecard.schema.json").validate(card)


# ---------------- 4) 对接 ---------------- #


def test_output_feeds_loop_controller():
    bad = _draft([_sec("现状痛点", "因此建议立刻更换全部质检设备。")])
    card = verify(bad, {})
    graph = compile_workflow(ROOT / "workflows" / "industry_solution.yaml")
    decision = LoopController(graph, _policy()).decide(card)
    assert decision.action in {"revise", "abort"}
    if decision.action == "revise":
        assert "write" in decision.targets
        assert "verify" in decision.rerun_nodes


def test_all_target_nodes_exist_in_workflow():
    workflow = yaml.safe_load(
        (ROOT / "workflows" / "industry_solution.yaml").read_text(encoding="utf-8")
    )
    node_ids = {
        str(node.get("id"))
        for node in (workflow.get("nodes") or [])
        if isinstance(node, dict)
    }
    assert {"write", "fanout"} <= node_ids
    for draft in (_good_draft(), _contradiction_draft()):
        for issue in judge(draft, EVIDENCE).issues:
            assert issue["target_node"] in node_ids
