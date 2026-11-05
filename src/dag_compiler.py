"""YAML → 已校验工作流图；普通依赖与 loop 回边分别保存。

compile_workflow(path) 返回节点表、前驱/后继、拓扑层和回边，供调度器接入。
拓扑层只描述依赖就绪关系；条件分派、执行和修订轮次由调度器/LoopController 处理。
"""
from __future__ import annotations

import ast
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

ROOT = Path(__file__).resolve().parents[1]


class WorkflowCompileError(ValueError):
    """可按 compile_error 契约序列化，同时兼容现有 ValueError 调用方。"""

    def __init__(self, code, message, *, node_id=None, field=None, path=None):
        self.code, self.message = code, message
        self.node_id, self.field, self.path = node_id, field, path
        super().__init__(f"{code}: {message}")

    def to_dict(self) -> dict:
        return {key: value for key, value in {
            "code": self.code, "message": self.message, "severity": "error",
            "node_id": self.node_id, "field": self.field, "path": self.path,
        }.items() if value is not None}


@dataclass
class CompiledWorkflow:
    """内存图；layers 不包含循环回边，也不表示条件后继能同时执行。"""

    name: str
    nodes: dict[str, dict]
    dependencies: dict[str, tuple[str, ...]]
    successors: dict[str, tuple[str, ...]]
    layers: tuple[tuple[str, ...], ...]
    loop: dict | None
    outputs: tuple[str, ...]

    @property
    def entry(self) -> str:
        return self.layers[0][0]

    @property
    def edges(self) -> tuple[tuple[str, str], ...]:
        return tuple((parent, child) for child, parents in self.dependencies.items() for parent in parents)


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
        raise WorkflowCompileError("SCHEMA_INVALID", "when 只允许数值比较及 and/or/not", field="when")


def validate_workflow(workflow: dict, agent_names: set[str] | None = None,
                      tool_names: set[str] | None = None) -> None:
    """检查 Schema、依赖图和显式回边；agent_names 由角色注册表提供。"""
    schema = json.loads((ROOT / "contracts/workflow.schema.json").read_text(encoding="utf-8"))
    error = next(Draft202012Validator(schema).iter_errors(workflow), None)
    if error:
        field = "/".join(map(str, error.path))
        code = "SCHEMA_INVALID"
        if error.validator == "minItems" and field == "nodes":
            code = "EMPTY_NODES"
        elif (error.validator == "enum" and field.endswith("/type")
              and error.instance not in schema["properties"]["nodes"]["items"]["properties"]["type"]["enum"]):
            code = "UNKNOWN_NODE_TYPE"
        elif error.validator == "required" and isinstance(error.instance, dict):
            for kind in ("agent", "tool"):
                if error.instance.get("type") == kind and kind not in error.instance:
                    code = f"MISSING_{kind.upper()}"
        elif field in {"loop/max_rounds", "loop/stop_if_no_gain_rounds"}:
            code = "CYCLE_OVER_LIMIT"
        raise WorkflowCompileError(code, error.message, field=field or "<root>")
    nodes = workflow["nodes"]
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        raise WorkflowCompileError("BAD_DEPENDS_ON", "节点 id 重复", field="nodes")
    graph = {node["id"]: set(node.get("depends_on", [])) for node in nodes}
    for node in nodes:
        node_id = node["id"]
        if graph[node_id] - by_id.keys() or node_id in graph[node_id]:
            raise WorkflowCompileError("BAD_DEPENDS_ON", "存在悬空或自身依赖", node_id=node_id, field="depends_on")
        if agent_names is not None and node["type"] == "agent" and node["agent"] not in agent_names:
            raise WorkflowCompileError("MISSING_AGENT", f"未注册角色：{node['agent']!r}", node_id=node_id, field="agent")
        if tool_names is not None and node["type"] == "tool" and node["tool"] not in tool_names:
            raise WorkflowCompileError("MISSING_TOOL", f"未注册工具：{node['tool']!r}", node_id=node_id, field="tool")
        if "when" in node:
            try:
                validate_when(node["when"])
            except WorkflowCompileError as exc:
                raise WorkflowCompileError(exc.code, exc.message, node_id=node_id, field="when") from exc
    if sum(not deps for deps in graph.values()) != 1:
        raise WorkflowCompileError("BAD_DEPENDS_ON", "必须且只能有一个入口；空依赖不表示隐式并行")
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise WorkflowCompileError("BAD_DEPENDS_ON", "depends_on 不能成环，回边只能由 loop 声明") from exc
    loops = {node["id"] for node in nodes if node["type"] == "loop"}
    loop = workflow.get("loop")
    if not loop:
        if loops:
            raise WorkflowCompileError("SCHEMA_INVALID", "loop 节点缺少回边声明", field="loop")
        return
    if loops != {loop["from"]} or loop["to"] not in by_id:
        raise WorkflowCompileError("BAD_DEPENDS_ON", "loop 端点不存在或 from 不是唯一 loop 节点", field="loop")
    ancestors, pending = set(), list(graph[loop["from"]])
    while pending:
        current = pending.pop()
        if current not in ancestors:
            ancestors.add(current)
            pending.extend(graph[current])
    if loop["to"] not in ancestors:
        raise WorkflowCompileError("BAD_DEPENDS_ON", "loop.to 必须是 loop.from 的前驱节点", field="loop/to")


def compile_workflow(source: str | Path | dict, *, agent_names: set[str] | None = None,
                     tool_names: set[str] | None = None) -> CompiledWorkflow:
    """读取 YAML 文件或配置 dict，生成图；默认核对仓库角色与工具注册表。

    source 为文件路径（相对路径以调用方当前目录为准）或已解析配置，不接受 YAML 文本。
    返回图与调用方输入隔离，loop 原样保留 fanout/3/2 等契约值，不混进普通依赖。
    调用方可提供注册表名称集合用于独立模板；空集合表示不允许任何该类节点。
    """
    path = None
    try:
        if isinstance(source, dict):
            workflow = deepcopy(source)
        else:
            path = str(Path(source))
            workflow = yaml.safe_load(Path(source).read_text(encoding="utf-8-sig"))
        if agent_names is None:
            agent_names = set()
            for config in sorted((ROOT / "agents").glob("*.yaml")):
                role = yaml.safe_load(config.read_text(encoding="utf-8-sig"))
                if not isinstance(role, dict) or not isinstance(role.get("name"), str):
                    raise WorkflowCompileError("MISSING_AGENT", "角色配置缺少 name", path=str(config))
                agent_names.add(role["name"])
        if tool_names is None:
            if __package__:
                from .tools.registry import list_tools
            else:
                from tools.registry import list_tools
            tool_names = set(list_tools())
        validate_workflow(workflow, agent_names, tool_names)
    except WorkflowCompileError as exc:
        if exc.path is None:
            exc.path = path
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkflowCompileError("SCHEMA_INVALID", str(exc), path=path) from exc
    nodes = {node["id"]: node for node in workflow["nodes"]}
    dependencies = {key: tuple(node.get("depends_on", [])) for key, node in nodes.items()}
    successors = {key: [] for key in nodes}
    for child, parents in dependencies.items():
        for parent in parents:
            successors[parent].append(child)
    sorter = TopologicalSorter(dependencies)
    sorter.prepare()
    layers = []
    while sorter.is_active():
        ready = tuple(sorted(sorter.get_ready()))
        layers.append(ready)
        sorter.done(*ready)
    return CompiledWorkflow(
        workflow["name"], nodes, dependencies,
        {key: tuple(sorted(children)) for key, children in successors.items()},
        tuple(layers), workflow.get("loop"), tuple(workflow.get("outputs", [])),
    )
