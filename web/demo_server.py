"""D 的控制台与 A API 同源代理，默认仅监听 127.0.0.1:8765。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from src.dag_compiler import ROOT, compile_workflow
from src.trace import read_trace
from web.local_runtime import run_local
from web.mock_runtime import run_demo

WEB = Path(__file__).parent
FILES = {"solution.md", "scorecard.json", "evidence_chain.json", "evidence_refs.json", "trace.jsonl", "rounds.json", "delivery_artifact.json", "review_history.json", "charts/scorecard.svg", "charts/convergence.svg"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 请求/需求正文不写访问日志。

    def do_GET(self):
        parsed = urlparse(self.path)
        if re.fullmatch(r"/runs/[a-f0-9]{32}/(?:events|artifacts)", parsed.path):
            return self.proxy_api()
        match = re.fullmatch(r"/api/files/([a-f0-9]{32})/(.+)", parsed.path)
        if match:
            run_id, name = match.groups()
            if name not in FILES - {"review_history.json"}:
                return self.send_error(400)
            folder = ROOT / "outputs/api" / run_id
            target = folder / name
            if not target.is_file():
                return self.send_error(404)
            content = target.read_bytes()
            if name != "delivery_artifact.json":
                try:
                    manifest = json.loads((folder / "delivery_artifact.json").read_text(encoding="utf-8"))["manifest"]
                    entry = next((item for item in manifest["files"] if item["path"] == name), None)
                except (OSError, ValueError, KeyError, TypeError):
                    return self.send_error(409, "Artifact manifest unavailable")
                if not entry or entry["sha256"] != hashlib.sha256(content).hexdigest() or entry["bytes"] != len(content):
                    return self.send_error(409, "Artifact digest mismatch")
            mime = "image/svg+xml" if name.endswith(".svg") else "text/plain" if name.endswith((".md", ".jsonl")) else "application/json"
            return self.send_data(content, mime)
        if parsed.path == "/api/workflow":
            graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
            return self.send_data(json.dumps({"nodes": list(graph.nodes.values()), "loop": graph.loop,
                "source": (ROOT / "workflows/industry_solution.yaml").read_text(encoding="utf-8")}).encode(), "application/json")
        if parsed.path == "/api/replay/demo":
            target = ROOT / "outputs/demo/trace.jsonl"
            if not target.is_file():
                return self.send_error(404, "Run python -m src.run --output outputs/demo first")
            return self.send_data(json.dumps(read_trace(target)).encode(), "application/json")
        if parsed.path == "/download":
            args = parse_qs(parsed.query)
            run, name = args.get("run", [""])[0], args.get("file", [""])[0]
            if not re.fullmatch(r"[a-f0-9]{32}", run) or name not in FILES:
                return self.send_error(400)
            target = ROOT / "outputs/d-console" / run / name
            if not target.is_file():
                return self.send_error(404)
            return self.send_data(target.read_bytes(), "application/octet-stream", name)
        name = {"/": "index.html", "/app.js": "app.js", "/trace_view.js": "trace_view.js", "/style.css": "style.css"}.get(parsed.path)
        if name is None:
            return self.send_error(404)
        mime = {"index.html": "text/html", "app.js": "text/javascript", "trace_view.js": "text/javascript", "style.css": "text/css"}[name]
        self.send_data((WEB / name).read_bytes(), mime)

    def send_data(self, data, mime, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path == "/runs":
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                return self.send_error(403)
            return self.proxy_api()
        if self.path not in {"/api/run", "/api/run-real"} or self.headers.get_content_type() != "application/json":
            return self.send_error(400)
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.send_error(403)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 20000:
                raise ValueError("无效请求长度")
            data = json.loads(self.rfile.read(length))
            allowed = {"request"} if self.path == "/api/run-real" else {"request", "scenario", "engine"}
            if not isinstance(data, dict) or set(data) - allowed:
                raise ValueError("无效请求字段")
            if not isinstance(data.get("request"), str) or not 0 < len(data["request"].strip()) <= 4000:
                raise ValueError("需求不能为空且最多 4000 字")
        except (ValueError, TypeError):
            return self.send_error(400)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        lock = Lock()

        def send(kind, value):
            payload = f"event: {kind}\ndata: {json.dumps(value, ensure_ascii=False)}\n\n".encode("utf-8")
            try:
                with lock:
                    self.wfile.write(payload)
                    self.wfile.flush()
            except OSError:  # 浏览器断开不应打断纵切或交付物落盘。
                pass
        folder = uuid4().hex
        try:
            options = {"output": ROOT / "outputs/d-console" / folder,
                       "emit": lambda item: send("trace", item)}
            if self.path == "/api/run-real":
                result = run_local(**data, **options, publish=lambda item: send("review", item))
            else:
                result = run_demo(**data, **options)  # 兼容明确选择的旧评分桩测试。
            result["download_id"] = folder
            send("result", result)
        except Exception as exc:
            send("error", {"message": str(exc)})

    def proxy_api(self):
        """固定上游的同源转发；逐块传递 A 的实际 SSE，不执行本地运行时。"""
        base = urlparse(getattr(self.server, "api_base", "http://127.0.0.1:8000"))
        connection = (HTTPSConnection if base.scheme == "https" else HTTPConnection)(base.hostname, base.port, timeout=180)
        sent = False
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 <= length <= 20000:
                return self.send_error(400)
            body = self.rfile.read(length) if self.command == "POST" else None
            connection.request(self.command, self.path, body=body,
                               headers={"Content-Type":"application/json", "Accept":"text/event-stream, application/json"})
            response = connection.getresponse()
            sent = True
            self.send_response(response.status)
            self.send_header("Content-Type", response.getheader("Content-Type", "application/json"))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, ValueError):
            if not sent:
                self.send_error(502, "Start the API: python -m uvicorn src.main:app")
            self.close_connection = True
        finally:
            connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(f"ChainGuard D 本机纵切控制台：http://127.0.0.1:{args.port}")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.api_base = args.api_base
    server.serve_forever()
