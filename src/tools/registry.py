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


def is_registered(name: str) -> bool:
    """工具名是否已注册。"""
    return name in TOOLS


def list_tools() -> list[str]:
    """按字母序列出全部工具名（稳定输出，便于测试与 diff）。"""
    return sorted(TOOLS)


def unknown_tools(names: list[str]) -> list[str]:
    """返回 `names` 中未注册的那些（保持输入顺序，便于定位是哪个角色写错了）。"""
    return [n for n in names if n not in TOOLS]
