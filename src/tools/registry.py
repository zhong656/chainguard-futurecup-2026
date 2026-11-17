"""工具注册表 —— 全仓库工具名的唯一事实来源。

契约约定（`contracts/agent_spec.schema.json`）：
    `agents/*.yaml` 的 `tools` 只能引用本表已注册的名字，否则视为非法配置。

为什么需要它
------------
之前 6 份角色 YAML 里写的 `knowledge_retrieve`、`python_sandbox` 等名字，
没有任何地方校验它们是否真实存在——契约里承诺的 `MISSING_TOOL` 错误码
因此形同虚设（见 `contracts/compile_error.schema.json`）。
本文件把这些名字固定下来，`scripts/check_contracts.py` 才能做子集校验。

Owner: B（知识库与工具）
冻结: 2026-11-07 22:00（新增工具走 contract-change PR）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    """一个工具的元信息。`impl` 为空表示尚未实现（阶段 1 补）。"""

    name: str
    description: str
    read_only: bool
    owner: str
    impl: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "read_only": self.read_only,
            "owner": self.owner,
            "impl": self.impl,
        }


# 8 个工具名冻结（与 6 份角色 YAML 的 tools 字段一一对应）
_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="knowledge_retrieve",
        description="在知识库中检索证据片段，返回 retrieval_result（含 source_id 与 score）",
        read_only=True,
        owner="B",
        impl="src/tools/retrieve.py",
    ),
    ToolSpec(
        name="doc_parse",
        description="解析 PDF / DOCX / Markdown 为纯文本与分页结构",
        read_only=True,
        owner="B",
        impl="src/tools/parse.py",
    ),
    ToolSpec(
        name="web_fetch_optional",
        description="联网抓取网页摘录（可选增强，Mock 模式下禁用）",
        read_only=True,
        owner="B",
        impl="src/tools/fetch.py",
    ),
    ToolSpec(
        name="python_sandbox",
        description="受限 Python 执行（子进程 + 超时 + 导入白名单），用于数值测算与绘图",
        read_only=False,
        owner="B",
        impl="src/sandbox.py",
    ),
    ToolSpec(
        name="chart_render",
        description="渲染图表为图片文件，供方案书引用",
        read_only=False,
        owner="B",
        impl="src/tools/chart.py",
    ),
    ToolSpec(
        name="template_render",
        description="按六章模板渲染结构化方案书，强制回填 source_id",
        read_only=False,
        owner="C",
        impl="src/tools/template.py",
    ),
    ToolSpec(
        name="rule_verifier",
        description="确定性规则校验（引用真实性 / 数值一致性 / 章节完整性 / Schema）",
        read_only=True,
        owner="C",
        impl="src/rule_checker.py",
    ),
    ToolSpec(
        name="trace_read",
        description="只读读取 Trace 事件流，用于终审与重放",
        read_only=True,
        owner="D",
        impl="src/trace.py",
    ),
)

TOOLS: dict[str, ToolSpec] = {t.name: t for t in _TOOLS}

# 外部工具（MCP 接入）走独立字典：静态 8 个工具的名字仍然冻结，
# 外部工具用 `mcp:<server>:<tool>` 命名空间，避免与内置重名。
_EXTERNAL: dict[str, ToolSpec] = {}

MCP_PREFIX = "mcp:"


def register_external(spec: ToolSpec) -> None:
    """注册一个外部（MCP）工具。

    约束：
      1. 名字必须是 `mcp:` 前缀——外部工具不该占用内置命名；
      2. 不得与已注册的名字冲突（重名会让"谁负责"变模糊）；
      3. **默认按"可写"对待**（read_only=False），除非调用方显式声明只读。
         保守方向：宁可让只读 Agent 用不了，也不让有副作用的工具被只读角色调用。
    """
    if not spec.name.startswith(MCP_PREFIX):
        raise ValueError(f"外部工具名必须以 {MCP_PREFIX} 开头：{spec.name}")
    if spec.name in TOOLS or spec.name in _EXTERNAL:
        raise ValueError(f"工具名已存在，不能重复注册：{spec.name}")
    _EXTERNAL[spec.name] = spec


def unregister_external(name: str) -> None:
    _EXTERNAL.pop(name, None)


def external_tools() -> dict[str, ToolSpec]:
    return dict(_EXTERNAL)


def is_registered(name: str) -> bool:
    """工具名是否已注册（含外部工具）。"""
    return name in TOOLS or name in _EXTERNAL


def list_tools() -> list[str]:
    """按字母序列出全部工具名（稳定输出，便于测试与 diff）。"""
    return sorted([*TOOLS, *_EXTERNAL])


def unknown_tools(names: list[str]) -> list[str]:
    """返回 `names` 中未注册的那些（保持输入顺序，便于定位是哪个角色写错了）。"""
    return [n for n in names if not is_registered(n)]
