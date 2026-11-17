"""MCP 桥接：把外部 MCP 服务器的工具接进编排层的工具注册表（Owner: B）。

它解决什么
----------
MCP 客户端（`src/mcp/client.py`）能连上服务器、列举与调用工具；
但编排层只认 `src/tools/registry.py` 里的工具名。
本模块是两者之间的那一层：

    连接服务器 → tools/list → 注册为 `mcp:<server>:<tool>` → 可被 agents/*.yaml 引用
    调用工具   → call_tool  → 路由回对应服务器

命名与安全
----------
- 命名空间 `mcp:<server>:<tool>`：不会与 8 个内置工具重名；
- **默认按可写注册**（read_only=False）：MCP 工具的行为我们不可控，
  宁可让只读角色用不了，也不能让有副作用的工具被只读 Agent 调用；
- 连接失败不静默：抛 `MCPError`，由调用方决定是降级还是报错。

用法
----
    from src.mcp.bridge import MCPBridge

    with MCPBridge() as bridge:
        bridge.attach("calc", "mcp_servers/calc_server.py")
        bridge.call("mcp:calc:add", {"a": 2, "b": 40})   # → "42.0"

    # 或命令行
    python -m src.mcp.bridge --server calc mcp_servers/calc_server.py --list
    python -m src.mcp.bridge --server calc mcp_servers/calc_server.py \
        --call add --args '{"a": 2, "b": 40}'
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.mcp.client import MCPClient, MCPError, launch
from src.tools.registry import ToolSpec, is_registered, register_external, unregister_external

ROOT = Path(__file__).resolve().parents[2]


class MCPBridge:
    """管理若干 MCP 连接，并把它们的工具注册进工具表。"""

    def __init__(self) -> None:
        self._clients: dict[str, MCPClient] = {}
        self._routes: dict[str, tuple[str, str]] = {}   # 全名 → (server, tool)

    # ── 生命周期 ─────────────────────────────────────────
    def __enter__(self) -> "MCPBridge":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for name, client in self._clients.items():
            client.close()
            for full, (server, _tool) in list(self._routes.items()):
                if server == name:
                    unregister_external(full)
                    self._routes.pop(full, None)
        self._clients.clear()

    # ── 接入 ────────────────────────────────────────────
    def attach(self, server: str, script: str | Path, *, read_only: bool = False) -> list[str]:
        """启动服务器、列举工具并注册；返回注册出来的工具全名。"""
        if server in self._clients:
            raise MCPError(f"服务器已接入：{server}")
        client = launch(str(script))
        try:
            client.start()
            tools = client.list_tools()
        except Exception:
            client.close()
            raise

        registered: list[str] = []
        for tool in tools:
            full = f"mcp:{server}:{tool.name}"
            if is_registered(full):
                continue
            register_external(ToolSpec(
                name=full,
                description=f"[MCP:{server}] {tool.description or tool.name}",
                read_only=read_only,
                owner="B",
                impl=f"mcp:{server}",
            ))
            self._routes[full] = (server, tool.name)
            registered.append(full)

        self._clients[server] = client
        return registered

    # ── 调用 ────────────────────────────────────────────
    def call(self, full_name: str, arguments: dict | None = None) -> str:
        """按注册的全名路由到对应服务器并取回文本结果。"""
        route = self._routes.get(full_name)
        if route is None:
            raise MCPError(f"未接入的工具：{full_name}（先用 attach 接入服务器）")
        server, tool = route
        client = self._clients[server]
        result = client.call_tool(tool, arguments or {})
        if result.is_error:
            raise MCPError(f"{full_name} 返回错误：{result.text}")
        return result.text

    # ── 查询 ────────────────────────────────────────────
    def routes(self) -> dict[str, tuple[str, str]]:
        return dict(self._routes)

    def tool_dicts(self) -> list[dict]:
        """给控制台 / Trace 展示用的工具清单。"""
        out = []
        for full, (server, tool) in sorted(self._routes.items()):
            out.append({"name": full, "server": server, "tool": tool})
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP 接入演示")
    parser.add_argument("--server", required=True, help="服务器名，用于 mcp:<server>:<tool> 命名")
    parser.add_argument("script", help="MCP 服务器脚本路径")
    parser.add_argument("--list", action="store_true", help="只列举工具")
    parser.add_argument("--call", help="要调用的工具名（不带命名空间）")
    parser.add_argument("--args", default="{}", help="调用参数（JSON）")
    args = parser.parse_args()

    with MCPBridge() as bridge:
        names = bridge.attach(args.server, args.script)
        print(f"[OK] 已接入 {args.server}：{len(names)} 个工具")
        for name in names:
            print(f"  · {name}")
        if args.list:
            return 0
        if args.call:
            try:
                payload = json.loads(args.args)
            except json.JSONDecodeError as exc:
                print(f"[FAIL] --args 不是合法 JSON：{exc}")
                return 1
            full = f"mcp:{args.server}:{args.call}"
            value = bridge.call(full, payload)
            print(f"[OK] {full} → {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
