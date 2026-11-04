"""工具层（Owner: B）。

`agents/*.yaml` 里 `tools` 字段引用的名字，必须存在于 `src/tools/registry.py`
的注册表中——这是 `contracts/agent_spec.schema.json` 的约定。

本包目前只有注册表，具体实现（检索、沙箱、图表等）在阶段 1 逐个补齐。
"""

from .registry import TOOLS, ToolSpec, is_registered, list_tools, unknown_tools

__all__ = ["TOOLS", "ToolSpec", "is_registered", "list_tools", "unknown_tools"]
