"""MCP 接入（Owner: B）。

只做一件事：把外部 MCP 服务器的工具**接进编排层的工具注册表**，
使 `agents/*.yaml` 能像引用内置工具一样引用它们。
"""

from .client import MCPCallResult, MCPClient, MCPError, MCPTool, launch

__all__ = ["MCPClient", "MCPError", "MCPTool", "MCPCallResult", "launch"]
