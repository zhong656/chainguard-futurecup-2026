"""一个自带的最小 MCP 服务器（演示 / 测试用，无第三方依赖）。

为什么仓库里要带一个 MCP 服务器
--------------------------------
只说"支持 MCP"很容易，**能不能真连上**才是关键。评审要验证这一点，
不应该要求他先去装某个官方 MCP server 或申请凭据。

所以这里用标准库实现一个最小可用的 MCP 服务器：换行分隔的 JSON-RPC 2.0，
走 stdin/stdout（stdio transport），实现三个必需方法：

    initialize  → 返回协议版本与能力
    tools/list  → 返回工具清单（含 JSON Schema）
    tools/call  → 执行工具并返回 content

工具：`add` / `multiply`（纯计算，可离线验证）。

协议依据：MCP 规范（JSON-RPC 2.0 + stdio transport）。
**已知边界**：只实现 tools 能力，未实现 resources / prompts / sampling；
只支持 stdio，未实现 HTTP+SSE transport；不做鉴权。见 docs/方案书 §8.3。
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "chainguard-demo-calc", "version": "1.0.0"}


def _add(a: float, b: float) -> float:
    return a + b


def _multiply(a: float, b: float) -> float:
    return a * b


TOOLS: dict[str, tuple[Callable[..., float], str, dict]] = {
    "add": (
        _add,
        "两数相加",
        {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    ),
    "multiply": (
        _multiply,
        "两数相乘",
        {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    ),
}


def handle(request: dict) -> dict | None:
    """处理一条 JSON-RPC 请求；通知（无 id）返回 None。"""
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "notifications/initialized":
        return None  # 通知不需要响应

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {"name": name, "description": desc, "inputSchema": schema}
                    for name, (_, desc, schema) in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"未知工具：{name}"},
            }
        func, _, schema = TOOLS[name]
        missing = [k for k in schema.get("required", []) if k not in arguments]
        if missing:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"缺少参数：{missing}"},
            }
        try:
            value = func(**{k: float(arguments[k]) for k in schema["properties"]})
        except (TypeError, ValueError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": f"参数错误：{exc}"}],
                           "isError": True},
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": str(value)}], "isError": False},
        }

    # 未知方法：JSON-RPC 规定返回 -32601
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"未实现的方法：{method}"},
    }


def serve(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()


if __name__ == "__main__":
    serve()
