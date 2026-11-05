import copy
from pathlib import Path

import pytest
import yaml

from src.dag_compiler import compile_workflow
from src.loop_controller import LoopController

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def controller():
    graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
    policy = yaml.safe_load((ROOT / "configs/verifier.yaml").read_text(encoding="utf-8"))["scorecard"]
    return LoopController(graph, policy)


def card(round=0, score=0.75, targets=("write",), verdict="fail"):
    return {
        "run_id": "test-run", "round": round, "score": score, "threshold": 0.85,
        "metrics": {key: score for key in ["citation", "consistency", "coverage", "logic", "format"]},
        "issues": [{"section": "3.2", "reason": "示例错误", "suggestion": "修订该段",
                    "target_node": target, "severity": "warning"} for target in targets],
        "verdict": verdict,
    }


def test_targeted_revision_preserves_other_branch(controller):
    decision = controller.decide(card(targets=("analyze",)))
    assert decision.action == "revise" and decision.round == 1
    assert decision.rerun_nodes == ("analyze", "write", "verify")
    assert "outline" not in decision.rerun_nodes


def test_default_target_is_fanout(controller):
    decision = controller.decide(card(targets=()))
    assert decision.targets == ("fanout",)
    assert decision.rerun_nodes == ("fanout", "analyze", "outline", "write", "verify")


def test_multiple_issues_merge_downstream(controller):
    decision = controller.decide(card(targets=("write", "analyze", "write")))
    assert decision.rerun_nodes == ("analyze", "write", "verify")


def test_fail_then_pass(controller):
    assert controller.decide(card()).action == "revise"
    assert controller.decide(card(1, 0.9, (), "pass")).action == "pass"


def test_three_round_limit(controller):
    for round, score in enumerate([0.65, 0.70, 0.75]):
        assert controller.decide(card(round, score)).action == "revise"
    decision = controller.decide(card(3, 0.80))
    assert decision.action == "abort" and "三轮" in decision.reason


def test_two_rounds_without_gain(controller):
    controller.decide(card(0, 0.8))
    controller.decide(card(1, 0.79))
    assert "无提升" in controller.decide(card(2, 0.80)).reason


@pytest.mark.parametrize("veto", ["blocker", "low_metric", "failed_verdict"])
def test_high_score_cannot_override_veto(controller, veto):
    data = card(score=0.95, verdict="pass")
    if veto == "blocker":
        data["issues"][0]["severity"] = "blocker"
    elif veto == "low_metric":
        data["metrics"]["citation"] = 0.59
    else:
        data["verdict"] = "fail"
    assert controller.decide(data).action == "revise"


@pytest.mark.parametrize("target", ["missing", "review", "gate", "snap", "verify"])
def test_invalid_target_rejected(controller, target):
    with pytest.raises(ValueError, match="target_node"):
        controller.decide(card(targets=(target,)))


def test_wrong_round_and_missing_metrics(controller):
    with pytest.raises(ValueError, match="round"):
        controller.decide(card(1))
    data = copy.deepcopy(card())
    del data["metrics"]["logic"]
    with pytest.raises(ValueError, match="五维"):
        controller.decide(data)


def test_invalid_target_does_not_consume_round_or_history(controller):
    with pytest.raises(ValueError):
        controller.decide(card(targets=("missing",)))
    assert controller.round == 0 and controller.best_score == -1 and controller.no_gain == 0
    assert controller.decide(card()).round == 1


def test_round_three_can_still_pass(controller):
    for round, score in enumerate([0.65, 0.70, 0.75]):
        controller.decide(card(round, score))
    assert controller.decide(card(3, 0.90, (), "pass")).action == "pass"
