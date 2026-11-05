import pytest

pytest.importorskip("langgraph.graph", reason="可选运行时：安装 langgraph 后执行真实编译测试")

from src.dag_compiler import ROOT, compile_langgraph, compile_workflow


@pytest.mark.parametrize("action,visited,skipped", [
    ("pass", "review", "revise"), ("revise", "revise", "review"), ("abort", "gate", "snap"),
])
def test_real_langgraph_branches(action, visited, skipped):
    graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
    handlers = {node: (lambda state: {"done": True}) for node in graph.nodes}
    handlers["gate"] = lambda state: {"action": action}
    executable = compile_langgraph(graph, handlers)
    result = executable.invoke({"request": "Mock", "run_id": "r", "trace_id": "t", "round": 0, "results": {}})
    assert visited in result["results"] and skipped not in result["results"]
    assert {"analyze", "outline", "write", "verify"} <= result["results"].keys()


def test_targeted_subgraph_reuses_unaffected_results():
    graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
    handlers = {node: (lambda state: {"done": True}) for node in graph.nodes}
    handlers["gate"] = lambda state: {"action": "pass"}
    active = {"analyze", "write", "verify", "gate", "review", "revise", "snap"}
    previous = {node: {"cached": True} for node in graph.nodes if node not in active}
    result = compile_langgraph(graph, handlers, active_nodes=active).invoke({
        "request": "Mock", "run_id": "r", "trace_id": "t", "round": 1, "results": previous,
    })
    assert result["results"]["outline"] == {"cached": True}
    assert result["results"]["write"] == {"done": True}
