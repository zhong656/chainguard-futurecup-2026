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
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
# 我们**只实现**这一版协议：服务器回别的版本时不能假装握手成功——
# 版本不同意味着 capability 与字段语义都可能不同。
SUPPORTED_PROTOCOL_VERSIONS: frozenset[str] = frozenset({PROTOCOL_VERSION})
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
        self.last_exit_code: int | None = None
        self._cwd = cwd or ROOT

    # ── 生命周期 ─────────────────────────────────────────
    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        self._lines: queue.Queue[str] = queue.Queue()
        self._reader: threading.Thread | None = None

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
        # 后台读线程：把 stdout 逐行塞进队列。
        # 为什么要线程：`stdout.readline()` 是**阻塞**的，服务器卡住就永久挂起，
        # `self.timeout` 形同虚设（A 在 review 里指出的问题）。
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

        # **整段握手**都必须在 try 里：`with MCPClient(...)` 的 __enter__ 抛异常时，
        # Python 不会调用 __exit__，子进程会一直挂着（A 在 #91 复审里两次复现：
        # 先是 initialize 超时，后是 result 非对象时 .get() 抛错——两者都在 try 外）。
        # 因此从请求到解析到通知，任何一步失败都自己 close() 后再抛。
        try:
            self._handshake()
        except Exception:
            self.close()
            raise

    def _handshake(self) -> None:
        """initialize → 解析 → notifications/initialized，任一步失败都算握手失败。"""
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "chainguard-mcp-client", "version": "1.0.0"},
        })
        # 服务器可能返回 result: [] 或 "ok" 这类非对象——此时 .get() 会抛
        # AttributeError，若不在保护范围内就会泄漏子进程。
        if not isinstance(result, dict):
            raise MCPError(
                f"initialize 返回了非对象结果（{type(result).__name__}），不符合 MCP 协议"
            )
        # initialize 的三个字段都是**必填**（MCP 规范 InitializeResult）：
        # 只查类型不够——空字符串是合法 str，缺字段会拿到默认值，
        # 两种情况都会让"什么都没协商成"的握手被当成成功（A 在复审里复现）。
        protocol_version = result.get("protocolVersion")
        if not isinstance(protocol_version, str) or not protocol_version.strip():
            raise MCPError(
                f"initialize.protocolVersion 缺失或为空（{type(protocol_version).__name__}），"
                "无法确认协议版本"
            )
        if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise MCPError(
                f"不支持的协议版本：{protocol_version!r}；"
                f"本客户端只支持 {sorted(SUPPORTED_PROTOCOL_VERSIONS)}"
            )

        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict):
            raise MCPError(
                f"initialize.capabilities 缺失或非对象（{type(capabilities).__name__}）"
            )

        server_info = result.get("serverInfo")
        if not isinstance(server_info, dict):
            raise MCPError(
                f"initialize.serverInfo 缺失或非对象（{type(server_info).__name__}）"
            )
        name = server_info.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MCPError("initialize.serverInfo.name 缺失或为空，无法确认对端身份")

        self.protocol_version = protocol_version
        self.server_info = server_info
        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        finally:
            # 记下退出码：None 表示"没等到它退出"，供测试与排障断言
            self.last_exit_code = proc.poll()
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

    def _pump(self) -> None:
        """后台线程：把服务器 stdout 逐行放进队列；EOF 时放哨兵 None。"""
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                self._lines.put(line)
        except (ValueError, OSError):
            pass
        finally:
            self._lines.put("")  # EOF 哨兵

    def _readline(self, timeout: float | None = None) -> str:
        """从队列取一行；**超时就抛错**，不阻塞整个调用链。"""
        limit = self.timeout if timeout is None else timeout
        try:
            line = self._lines.get(timeout=limit)
        except queue.Empty as exc:
            raise MCPError(
                f"MCP 服务器 {limit:.1f}s 内无响应（方法超时）"
            ) from exc
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
