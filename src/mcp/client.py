"""最小 MCP 客户端（stdio transport，JSON-RPC 2.0，零第三方依赖）。

为什么自己实现而不引官方 SDK
----------------------------
1. **零依赖**：评审只需 Python 就能跑通，不用 pip 装 `mcp` 包；
2. **可审计**：走的就是 JSON-RPC 文本，评审可以直接 `cat` trace 看到每一条请求；
3. 我们只用 tools 能力，协议面很小，自己实现比引依赖更可控。

协议要点（MCP 2024-11-05）
--------------------------
    握手：initialize → notifications/initialized
    列举：tools/list      → [{name, description, inputSchema}]
    调用：tools/call      → {content: [{type: "text", text: ...}], isError: bool}

**已知边界**：仅 stdio transport；未实现 resources / prompts / sampling；
未实现 HTTP+SSE；无鉴权。这些限制写在 `docs/方案书-正文.md` §8.3。
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
ROOT = Path(__file__).resolve().parents[2]


class MCPError(RuntimeError):
    """MCP 协议或调用错误。"""


@dataclass(frozen=True)
class MCPTool:
    """从服务器列举出来的一个工具。"""

    name: str
    description: str
    input_schema: dict

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "inputSchema": self.input_schema}


@dataclass(frozen=True)
class MCPCallResult:
    text: str
    is_error: bool


class MCPClient:
    """一条 stdio 连接的 MCP 客户端。

    用法：
        with MCPClient([sys.executable, "mcp_servers/calc_server.py"]) as c:
            tools = c.list_tools()
            print(c.call_tool("add", {"a": 1, "b": 2}).text)
    """

    def __init__(self, command: list[str], *, cwd: Path | None = None,
                 timeout: float = 10.0, name: str = "mcp"):
        self.command = command
        self.timeout = timeout
        self.name = name
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._seq = 0
        self.server_info: dict = {}
        self.protocol_version: str = ""
        self._cwd = cwd or ROOT

    # ── 生命周期 ─────────────────────────────────────────
    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self.command,
            cwd=str(self._cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "chainguard-mcp-client", "version": "1.0.0"},
        })
        self.protocol_version = result.get("protocolVersion", "")
        self.server_info = result.get("serverInfo", {})
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self._proc.kill()
            except OSError:
                pass
        finally:
            self._proc = None

    # ── 协议 ────────────────────────────────────────────
    def _send(self, payload: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP 客户端未启动")
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPError(f"MCP 服务器已断开：{exc}") from exc

    def _readline(self) -> str:
        if self._proc is None or self._proc.stdout is None:
            raise MCPError("MCP 客户端未启动")
        line = self._proc.stdout.readline()
        if not line:
            raise MCPError("MCP 服务器没有返回（进程可能已退出）")
        return line

    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            self._seq += 1
            req_id = self._seq
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            while True:
                raw = self._readline()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise MCPError(f"MCP 返回非 JSON：{raw[:80]}") from exc
                # 服务器主动推送的通知没有 id，跳过
                if message.get("id") != req_id:
                    continue
                if "error" in message:
                    err = message["error"]
                    raise MCPError(f"{method} 失败：{err.get('message')}（code={err.get('code')}）")
                return message.get("result", {})

    def _notify(self, method: str, params: dict) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # ── 能力 ────────────────────────────────────────────
    def list_tools(self) -> list[MCPTool]:
        result = self._request("tools/list", {})
        return [
            MCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema") or {},
            )
            for t in result.get("tools", [])
        ]

    def call_tool(self, name: str, arguments: dict | None = None) -> MCPCallResult:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        parts = [
            item.get("text", "")
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return MCPCallResult(text="".join(parts), is_error=bool(result.get("isError")))


def launch(script: str, *, cwd: Path | None = None, timeout: float = 10.0) -> MCPClient:
    """用当前解释器启动一个仓库内的 MCP 服务器脚本。"""
    return MCPClient([sys.executable, script], cwd=cwd, timeout=timeout)
