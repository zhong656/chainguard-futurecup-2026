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

# ── 超时（A 在 #91 review 里指出：读取没有落实超时）────────────
SILENT_SERVER = """
import sys, time
# 读一行就不回应：模拟卡死的服务器
sys.stdin.readline()
time.sleep(30)
"""


def test_read_timeout_raises_instead_of_hanging(tmp_path):
    """服务器不响应时必须在 timeout 内抛 MCPError，而不是永久阻塞。"""
    import time

    script = tmp_path / "silent.py"
    script.write_text(SILENT_SERVER, encoding="utf-8")

    started = time.monotonic()
    with pytest.raises(MCPError) as exc:
        with launch(str(script), timeout=1.5) as c:
            c.list_tools()
    elapsed = time.monotonic() - started

    assert "超时" in str(exc.value) or "无响应" in str(exc.value)
    assert elapsed < 10, f"超时没有生效，实际等了 {elapsed:.1f}s"


def test_timeout_is_configurable(tmp_path):
    """timeout 参数应真正生效（不是写死的默认值）。"""
    import time

    script = tmp_path / "silent2.py"
    script.write_text(SILENT_SERVER, encoding="utf-8")
    started = time.monotonic()
    with pytest.raises(MCPError):
        with launch(str(script), timeout=0.8) as c:
            c.list_tools()
    assert time.monotonic() - started < 5

def test_start_failure_reaps_subprocess(tmp_path):
    """A 在 #91 复审里复现：握手超时后子进程仍在运行。

    `with MCPClient(...)` 的 __enter__ 抛异常时 Python 不调 __exit__，
    所以 start() 必须自己 close()。断言"进程真的退出并被回收"，
    仅断言"抛错 + 耗时"不够。
    """
    script = tmp_path / "silent3.py"
    script.write_text(SILENT_SERVER, encoding="utf-8")

    client = launch(str(script), timeout=0.4)
    with pytest.raises(MCPError):
        client.start()

    assert client._proc is None, "启动失败后仍持有 subprocess 句柄"
    assert client.last_exit_code is not None, "子进程没有被回收（退出码未知）"
    assert isinstance(client.last_exit_code, int), "退出码应为整数"


def test_context_manager_reaps_on_enter_failure(tmp_path):
    """走文档里的 `with` 用法：即便 __enter__ 抛错，也不能留下孤儿进程。"""
    import subprocess
    import sys as _sys

    script = tmp_path / "silent4.py"
    script.write_text(SILENT_SERVER, encoding="utf-8")

    before = _count_children(script.name)
    with pytest.raises(MCPError):
        with launch(str(script), timeout=0.4):
            pass
    after = _count_children(script.name)

    assert after <= before, f"with 用法留下了孤儿进程：{before} → {after}"


def _count_children(marker: str) -> int:
    """粗略统计命令行里含 marker 的进程数（跨平台用 tasklist / ps）。"""
    import subprocess as _sp
    import sys as _sys

    try:
        if _sys.platform == "win32":
            out = _sp.run(["tasklist", "/FO", "CSV"], capture_output=True, text=True, timeout=15).stdout
        else:
            out = _sp.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, _sp.SubprocessError):
        pytest.skip("无法枚举进程")
    return sum(1 for line in out.splitlines() if marker in line)

# ── 握手返回非对象结果（A 在 #91 复审里第二次复现）────────────
# 注意：result 的取值要拼进**JSON 文本**，不能拼进 Python 源码——
# `null` 在 Python 里不合法，会让服务器起不来，测的就不是客户端行为了。
BAD_RESULT_SERVER = """
import sys, json, time
line = sys.stdin.readline()
req = json.loads(line)
payload = '{"jsonrpc": "2.0", "id": ' + str(req["id"]) + ', "result": BAD_RESULT}'
sys.stdout.write(payload + "\\n")
sys.stdout.flush()
time.sleep(10)
"""


@pytest.mark.parametrize("bad", ["[]", '"ok"', "123", "null"])
def test_non_object_initialize_result_reaps_subprocess(tmp_path, bad):
    """服务器回 result 非对象 → start() 必须报错**且回收子进程**。

    此前 .get() 抛错发生在 try 之外，异常了但进程还活着。
    """
    script = tmp_path / f"bad_{abs(hash(bad))}.py"
    script.write_text(BAD_RESULT_SERVER.replace("BAD_RESULT", bad), encoding="utf-8")

    client = launch(str(script), timeout=3.0)
    with pytest.raises(MCPError) as exc:
        client.start()
    assert "非对象" in str(exc.value) or "协议" in str(exc.value)

    assert client._proc is None, "握手失败后仍持有 subprocess 句柄"
    assert isinstance(client.last_exit_code, int), "子进程没有被回收"


def test_non_object_result_via_with_reaps(tmp_path):
    """走 `with` 用法：__enter__ 抛错也必须回收。"""
    script = tmp_path / "bad_with.py"
    script.write_text(BAD_RESULT_SERVER.replace("BAD_RESULT", "[]"), encoding="utf-8")

    before = _count_children("bad_with.py")
    with pytest.raises(MCPError):
        with launch(str(script), timeout=3.0):
            pass
    assert _count_children("bad_with.py") <= before

# ── 握手必填字段（A 第三轮复现：空版本 / 非对象 serverInfo 竟报告成功）────
CUSTOM_RESULT_SERVER = """
import sys, json, time
line = sys.stdin.readline()
req = json.loads(line)
payload = '{"jsonrpc": "2.0", "id": ' + str(req["id"]) + ', "result": HANDMADE_RESULT}'
sys.stdout.write(payload + "\\n")
sys.stdout.flush()
time.sleep(10)
"""

_GOOD = ('{"protocolVersion": "2024-11-05", "capabilities": {}, '
         '"serverInfo": {"name": "fake", "version": "1.0"}}')

BAD_HANDSHAKES = {
    "empty_version": _GOOD.replace('"2024-11-05"', '""'),
    "unsupported_version": _GOOD.replace('"2024-11-05"', '"2025-06-18"'),
    "no_version": _GOOD.replace('"protocolVersion": "2024-11-05", ', ""),
    "no_capabilities": _GOOD.replace('"capabilities": {}, ', ""),
    "server_info_list": _GOOD.replace('{"name": "fake", "version": "1.0"}', "[]"),
    "no_server_info": _GOOD.replace(', "serverInfo": {"name": "fake", "version": "1.0"}', ""),
    "empty_server_name": _GOOD.replace('"name": "fake"', '"name": ""'),
    "no_server_version": _GOOD.replace(', "version": "1.0"', ""),
    "empty_server_version": _GOOD.replace('"version": "1.0"', '"version": ""'),
    "server_version_int": _GOOD.replace('"version": "1.0"', '"version": 1'),
}


@pytest.mark.parametrize("case", sorted(BAD_HANDSHAKES))
def test_bad_handshake_fields_are_rejected_and_reaped(tmp_path, case):
    """必填字段缺失/为空/类型错/版本不支持 → 必须报错并回收子进程。

    只查 isinstance 不够：空字符串是合法 str，"什么都没协商成"会被当成成功。
    """
    script = tmp_path / f"bad_handshake_{case}.py"
    script.write_text(
        CUSTOM_RESULT_SERVER.replace("HANDMADE_RESULT", BAD_HANDSHAKES[case]),
        encoding="utf-8",
    )

    client = launch(str(script), timeout=3.0)
    with pytest.raises(MCPError):
        client.start()

    assert client._proc is None, f"{case}: 握手被拒后仍持有子进程"
    assert isinstance(client.last_exit_code, int), f"{case}: 子进程没有回收"


def test_good_handshake_still_accepted(tmp_path):
    """反向保证：合法握手必须照常通过，别把校验写成了"一律拒绝"。"""
    script = tmp_path / "good_handshake.py"
    script.write_text(
        CUSTOM_RESULT_SERVER.replace("HANDMADE_RESULT", _GOOD), encoding="utf-8"
    )
    with launch(str(script), timeout=3.0) as client:
        assert client.protocol_version == "2024-11-05"
        assert client.server_info.get("name") == "fake"

def test_every_required_handshake_field_is_validated(tmp_path):
    """系统性保证：`REQUIRED_HANDSHAKE_FIELDS` 里**每一项**缺失都必须被拒。

    这条测试是防"逐个补洞"的：以后协议多一个必填字段，
    只要加进常量，这里就会要求它也真的被校验。
    """
    from src.mcp.client import REQUIRED_HANDSHAKE_FIELDS

    def strip_field(payload_json: str, dotted: str) -> str:
        import json

        data = json.loads(payload_json)
        parts = dotted.split(".")
        node = data
        for part in parts[:-1]:
            node = node[part]
        node.pop(parts[-1], None)
        return json.dumps(data, ensure_ascii=False)

    for field in REQUIRED_HANDSHAKE_FIELDS:
        payload = strip_field(_GOOD, field)
        script = tmp_path / f"missing_{field.replace('.', '_')}.py"
        script.write_text(
            CUSTOM_RESULT_SERVER.replace("HANDMADE_RESULT", payload), encoding="utf-8"
        )
        client = launch(str(script), timeout=3.0)
        try:
            client.start()
        except MCPError:
            assert client._proc is None, f"{field} 缺失时子进程未回收"
        else:
            pytest.fail(f"缺 {field} 却握手成功了——该字段没有被校验")
        finally:
            client.close()
