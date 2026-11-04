"""D 的拓扑、条件语法及跨契约节点接口验收。"""
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dag_compiler import validate_when, validate_workflow

ROLES = {"planner", "researcher", "analyst", "writer", "verifier", "reviewer"}


@pytest.fixture
def workflow():
    return yaml.safe_load((ROOT / "workflows/industry_solution.yaml").read_text(encoding="utf-8"))


def test_workflow_matches_example_and_roles(workflow):
    validate_workflow(workflow, ROLES)
    example = json.loads((ROOT / "contracts/examples/workflow.good.json").read_text(encoding="utf-8"))
    assert workflow == example
    assert {node["agent"] for node in workflow["nodes"] if node["type"] == "agent"} == ROLES
    for path in (ROOT / "agents").glob("*.yaml"):
        role = yaml.safe_load(path.read_text(encoding="utf-8"))
        if role is not None:  # main 的 C 配置仍是占位；合并后核对 name。
            assert role["name"] == path.stem
            assert role["name"] in ROLES


def test_scorecard_targets_exist(workflow):
    scorecard = json.loads((ROOT / "contracts/examples/scorecard.good.json").read_text(encoding="utf-8"))
    targets = {issue["target_node"] for issue in scorecard["issues"]}
    assert targets <= {node["id"] for node in workflow["nodes"]}
    assert {"analyze", "write"} <= {node["id"] for node in workflow["nodes"]}


def test_parallel_branches_join_before_write(workflow):
    nodes = {node["id"]: node for node in workflow["nodes"]}
    assert nodes["fanout"]["type"] == "parallel"
    assert nodes["analyze"]["depends_on"] == nodes["outline"]["depends_on"] == ["fanout"]
    assert set(nodes["write"]["depends_on"]) == {"analyze", "outline"}


@pytest.mark.parametrize("path,value", [
    (("nodes", 1, "depends_on"), ["absent"]),
    (("nodes", 1, "depends_on"), ["retrieve"]),
    (("nodes", 3, "depends_on"), ["write"]),
    (("nodes", 1, "depends_on"), []),
    (("nodes", 0, "agent"), None),
    (("nodes", 0, "agent"), "absent"),
    (("nodes", 0, "type"), "parallel_split"),
    (("nodes", 0), {"id": "plan", "type": "tool"}),
    (("nodes", 0, "when"), "score < threshold"),
    (("nodes", 7, "when"), None),
    (("loop",), None),
    (("loop", "to"), None),
    (("loop", "from"), "write"),
    (("loop", "to"), "snap"),
    (("loop", "max_rounds"), 4),
    (("loop", "stop_if_no_gain_rounds"), 3),
])
def test_invalid_graph_rejected(workflow, path, value):
    target = workflow
    for key in path[:-1]:
        target = target[key]
    if value is None:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_workflow(workflow, ROLES)


def test_duplicate_node_rejected(workflow):
    workflow["nodes"].append(dict(workflow["nodes"][0]))
    with pytest.raises(ValueError):
        validate_workflow(workflow, ROLES)


def test_single_root_may_omit_depends_on():
    validate_workflow({"name": "minimal", "nodes": [{"id": "start", "type": "checkpoint"}]})


@pytest.mark.parametrize("expression", [
    "score < threshold", "score < threshold and round < 3",
    "not (score >= threshold) or round == 0", "0 <= score <= 1",
])
def test_when_allowed(expression):
    validate_when(expression)


@pytest.mark.parametrize("expression", [
    "score", "score and round", "score < unknown", "score < threshold && round < 3",
    "__import__('os')", "score.real < threshold", "score + 1 < threshold",
    "score < True", "score < '0.85'", "score < 1e999", "",
])
def test_when_rejected(expression):
    with pytest.raises(ValueError, match="SCHEMA_INVALID"):
        validate_when(expression)
