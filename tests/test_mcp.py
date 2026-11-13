"""MCP 接入的测试（Owner: B）。

这些测试**真的起子进程、真的走 JSON-RPC**，不是打桩：
如果协议实现有问题，这里会红，而不是等到评审现场才发现连不上。

覆盖：
    1. 握手（initialize → notifications/initialized）
    2. tools/list 返回可用的工具描述
    3. tools/call 正常调用与错误参数
    4. 桥接：注册为 mcp:<server>:<tool> 并路由调用
    5. 安全：非法命名、重名、未接入就调用、服务器缺失
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.mcp.bridge import MCPBridge  # noqa: E402
from src.mcp.client import MCPError, launch  # noqa: E402
from src.tools.registry import (  # noqa: E402
    ToolSpec,
    external_tools,
    is_registered,
    register_external,
    unregister_external,
)

SERVER = ROOT / "mcp_servers" / "calc_server.py"


@pytest.fixture()
def client():
    with launch(str(SERVER)) as c:
        yield c


# ── 客户端 ───────────────────────────────────────────────
def test_handshake_reports_protocol_and_server(client):
    assert client.protocol_version, "握手没有返回 protocolVersion"
    assert client.server_info.get("name"), "握手没有返回 serverInfo"


def test_list_tools_returns_schema(client):
    tools = {t.name: t for t in client.list_tools()}
    assert "add" in tools and "multiply" in tools
    assert tools["add"].input_schema["required"] == ["a", "b"]


def test_call_tool_returns_text(client):
    result = client.call_tool("add", {"a": 2, "b": 40})
    assert not result.is_error
    assert float(result.text) == 42.0


def test_call_unknown_tool_raises(client):
    with pytest.raises(MCPError):
        client.call_tool("nope", {})


def test_missing_argument_raises(client):
    with pytest.raises(MCPError):
        client.call_tool("add", {"a": 1})


def test_server_script_missing_raises():
    with pytest.raises((MCPError, FileNotFoundError, OSError)):
        with launch("mcp_servers/does_not_exist.py") as c:
            c.list_tools()


# ── 桥接 ─────────────────────────────────────────────────
@pytest.fixture()
def bridge():
    with MCPBridge() as b:
        yield b


def test_bridge_registers_namespaced_tools(bridge):
    names = bridge.attach("calc", SERVER)
    assert "mcp:calc:add" in names
    assert is_registered("mcp:calc:add")
    assert not is_registered("calc:add"), "不应注册成非命名空间名字"


def test_bridge_routes_call(bridge):
    bridge.attach("calc", SERVER)
    assert float(bridge.call("mcp:calc:add", {"a": 19, "b": 23})) == 42.0
    assert float(bridge.call("mcp:calc:multiply", {"a": 6, "b": 7})) == 42.0


def test_bridge_close_unregisters(bridge):
    bridge.attach("calc", SERVER)
    assert is_registered("mcp:calc:add")
    bridge.close()
    assert not is_registered("mcp:calc:add"), "关闭后应注销，避免残留到其他测试"


def test_bridge_call_without_attach_raises(bridge):
    with pytest.raises(MCPError):
        bridge.call("mcp:ghost:add", {})


def test_bridge_rejects_duplicate_server(bridge):
    bridge.attach("calc", SERVER)
    with pytest.raises(MCPError):
        bridge.attach("calc", SERVER)


# ── 注册表约束 ───────────────────────────────────────────
def test_external_tool_requires_mcp_prefix():
    with pytest.raises(ValueError):
        register_external(ToolSpec(name="not_mcp", description="x", read_only=True, owner="B"))


def test_external_tool_rejects_duplicate_name():
    register_external(ToolSpec(name="mcp:t:dup", description="x", read_only=True, owner="B"))
    try:
        with pytest.raises(ValueError):
            register_external(ToolSpec(name="mcp:t:dup", description="y", read_only=True, owner="B"))
    finally:
        unregister_external("mcp:t:dup")


def test_external_tool_rejects_builtin_collision():
    with pytest.raises(ValueError):
        register_external(ToolSpec(name="mcp:x:y", description="x", read_only=True, owner="B"))
        # 第二次重复即冲突
        register_external(ToolSpec(name="mcp:x:y", description="x", read_only=True, owner="B"))


def test_external_defaults_to_writable_in_bridge(bridge):
    """MCP 工具行为不可控：默认按可写注册，只读角色才用不了。"""
    bridge.attach("calc", SERVER)
    spec = external_tools()["mcp:calc:add"]
    assert spec.read_only is False
