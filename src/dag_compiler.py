"""工作流的静态校验；执行器、条件分派与 LangGraph 编译在后续阶段接入。"""
from __future__ import annotations

import ast
import json
import math
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


def validate_when(expression: str) -> None:
    """只解析条件语法，不执行表达式；拒绝调用、属性和任意代码。"""
    def term(node):
        return (
            isinstance(node, ast.Name) and node.id in {"score", "threshold", "round"}
            or isinstance(node, ast.Constant)
            and type(node.value) in (int, float) and math.isfinite(node.value)
        )

    def condition(node):
        if isinstance(node, ast.BoolOp):
            return isinstance(node.op, (ast.And, ast.Or)) and all(map(condition, node.values))
        if isinstance(node, ast.UnaryOp):
            return isinstance(node.op, ast.Not) and condition(node.operand)
        return (
            isinstance(node, ast.Compare)
            and all(isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)) for op in node.ops)
            and all(map(term, [node.left, *node.comparators]))
        )

    try:
        valid = condition(ast.parse(expression, mode="eval").body)
    except (SyntaxError, ValueError, OverflowError, RecursionError):
        valid = False
    if not valid:
        raise ValueError("SCHEMA_INVALID: when 只允许数值比较及 and/or/not")


def validate_workflow(workflow: dict, agent_names: set[str] | None = None) -> None:
    """检查 Schema、依赖图和显式回边；agent_names 由角色注册表提供。"""
    schema = json.loads((ROOT / "contracts/workflow.schema.json").read_text(encoding="utf-8"))
    error = next(Draft202012Validator(schema).iter_errors(workflow), None)
    if error:
        raise ValueError(f"SCHEMA_INVALID: {error.message}")
    nodes = workflow["nodes"]
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("BAD_DEPENDS_ON: 节点 id 重复")
    graph = {node["id"]: set(node.get("depends_on", [])) for node in nodes}
    for node in nodes:
        node_id = node["id"]
        if graph[node_id] - by_id.keys() or node_id in graph[node_id]:
            raise ValueError(f"BAD_DEPENDS_ON: {node_id} 存在悬空或自身依赖")
        if agent_names is not None and node["type"] == "agent" and node["agent"] not in agent_names:
            raise ValueError(f"MISSING_AGENT: {node['agent']}")
        if "when" in node:
            validate_when(node["when"])
    if sum(not deps for deps in graph.values()) != 1:
        raise ValueError("BAD_DEPENDS_ON: 必须且只能有一个入口；空依赖不表示隐式并行")
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise ValueError("BAD_DEPENDS_ON: depends_on 不能成环，回边只能由 loop 声明") from exc
    loops = {node["id"] for node in nodes if node["type"] == "loop"}
    loop = workflow.get("loop")
    if not loop:
        if loops:
            raise ValueError("SCHEMA_INVALID: loop 节点缺少回边声明")
        return
    if loops != {loop["from"]} or loop["to"] not in by_id:
        raise ValueError("BAD_DEPENDS_ON: loop 端点不存在或 from 不是唯一 loop 节点")
    ancestors, pending = set(), list(graph[loop["from"]])
    while pending:
        current = pending.pop()
        if current not in ancestors:
            ancestors.add(current)
            pending.extend(graph[current])
    if loop["to"] not in ancestors:
        raise ValueError("BAD_DEPENDS_ON: loop.to 必须是 loop.from 的前驱节点")
