"""D 的拓扑、条件语法及跨契约节点接口验收。"""
import json
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dag_compiler import WorkflowCompileError, compile_workflow, validate_when, validate_workflow

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


def test_compile_yaml_builds_main_graph(workflow):
    graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
    assert graph == compile_workflow(workflow)
    assert graph.name == "industry_solution" and graph.entry == "plan"
    assert len(graph.nodes) == 11
    assert graph.dependencies["write"] == ("analyze", "outline")
    assert graph.successors["fanout"] == ("analyze", "outline")
    assert graph.successors["gate"] == ("review", "revise")
    assert ("analyze", "outline") in graph.layers
    positions = {key: i for i, layer in enumerate(graph.layers) for key in layer}
    assert all(positions[parent] < positions[child] for parent, child in graph.edges)
    assert graph.loop == {"from": "revise", "to": "fanout", "max_rounds": 3, "stop_if_no_gain_rounds": 2}
    assert ("revise", "fanout") not in graph.edges
    assert graph.nodes["gate"]["when"] == "score < threshold"
    assert graph.outputs == ("solution.md", "evidence_chain.json", "scorecard.json", "trace.jsonl")


def test_compile_is_deterministic_and_copies_input(workflow):
    graph = compile_workflow(workflow)
    workflow["nodes"].reverse()
    assert compile_workflow(workflow).layers == graph.layers
    workflow["nodes"].clear()
    workflow["loop"]["to"] = "absent"
    assert len(graph.nodes) == 11 and graph.loop["to"] == "fanout"
    graph.nodes["write"]["depends_on"].clear()
    assert graph.dependencies["write"] == ("analyze", "outline")


def test_compile_all_six_node_types(workflow):
    workflow["nodes"].insert(1, {
        "id": "parse", "type": "tool", "tool": "doc_parse", "depends_on": ["plan"],
    })
    workflow["nodes"][2]["depends_on"] = ["parse"]
    graph = compile_workflow(workflow)
    assert {node["type"] for node in graph.nodes.values()} == {
        "agent", "tool", "parallel", "condition", "loop", "checkpoint",
    }
    assert graph.dependencies["retrieve"] == ("parse",)


def test_compile_minimal_checkpoint():
    graph = compile_workflow({"name": "minimal", "nodes": [{"id": "start", "type": "checkpoint"}]})
    assert graph.layers == (("start",),)
    assert graph.edges == () and graph.loop is None and graph.outputs == ()


@pytest.mark.parametrize("node,code", [
    ({"id": "start", "type": "agent"}, "MISSING_AGENT"),
    ({"id": "start", "type": "agent", "agent": "unknown"}, "MISSING_AGENT"),
    ({"id": "start", "type": "tool"}, "MISSING_TOOL"),
    ({"id": "start", "type": "tool", "tool": "unknown"}, "MISSING_TOOL"),
    ({"id": "start", "type": "tool", "tool": ""}, "MISSING_TOOL"),
    ({"id": "start", "type": "unregistered"}, "UNKNOWN_NODE_TYPE"),
    ({"id": "start", "type": "checkpoint", "depends_on": ["absent"]}, "BAD_DEPENDS_ON"),
    ({"id": "start", "type": "condition", "when": "open('file')"}, "SCHEMA_INVALID"),
])
def test_compile_errors_follow_contract(node, code):
    with pytest.raises(WorkflowCompileError) as caught:
        compile_workflow({"name": "bad", "nodes": [node]})
    assert caught.value.code == code
    schema = json.loads((ROOT / "contracts/compile_error.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(caught.value.to_dict())


def test_compile_empty_nodes_and_loop_limits(workflow):
    with pytest.raises(WorkflowCompileError, match="EMPTY_NODES"):
        compile_workflow({"name": "bad", "nodes": []})
    workflow["loop"]["max_rounds"] = 4
    with pytest.raises(WorkflowCompileError, match="CYCLE_OVER_LIMIT"):
        compile_workflow(workflow)


@pytest.mark.parametrize("text", ["nodes: [", "", "- not_a_workflow", "name: missing_nodes"])
def test_compile_rejects_invalid_yaml(tmp_path, text):
    path = tmp_path / "invalid.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(WorkflowCompileError) as caught:
        compile_workflow(path)
    assert caught.value.code == "SCHEMA_INVALID"
    assert caught.value.to_dict()["path"] == str(path)


def test_compile_missing_file(tmp_path):
    with pytest.raises(WorkflowCompileError, match="SCHEMA_INVALID"):
        compile_workflow(tmp_path / "missing.yaml")


def test_compile_custom_registries():
    workflow = {"name": "custom", "nodes": [{"id": "start", "type": "agent", "agent": "custom_role"}]}
    assert compile_workflow(workflow, agent_names={"custom_role"}, tool_names=set()).entry == "start"
    with pytest.raises(WorkflowCompileError, match="MISSING_AGENT"):
        compile_workflow(workflow, agent_names=set())
