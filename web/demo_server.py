"""D 的本机 Mock 演示服务：python -m web.demo_server，默认仅监听 127.0.0.1:8765。

生产 API/FastAPI 由 A 接入；此服务用于无 Key 的可视化验收与 SSE 演示。
"""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from src.dag_compiler import ROOT, compile_workflow
from web.mock_runtime import run_demo

WEB = Path(__file__).parent
FILES = {"solution.md", "scorecard.json", "evidence_chain.json", "trace.jsonl", "delivery_artifact.json"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 请求/需求正文不写访问日志。

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/workflow":
            graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
            return self.send_data(json.dumps({"nodes": list(graph.nodes.values()), "loop": graph.loop}).encode(), "application/json")
        if parsed.path == "/download":
            args = parse_qs(parsed.query)
            run, name = args.get("run", [""])[0], args.get("file", [""])[0]
            if not re.fullmatch(r"[a-f0-9]{32}", run) or name not in FILES:
                return self.send_error(400)
            target = ROOT / "outputs/d-console" / run / name
            if not target.is_file():
                return self.send_error(404)
            return self.send_data(target.read_bytes(), "application/octet-stream", name)
        name = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}.get(parsed.path)
        if name is None:
            return self.send_error(404)
        mime = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}[name]
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
        if self.path != "/api/run" or self.headers.get_content_type() != "application/json":
            return self.send_error(400)
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self.send_error(403)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 20000:
                raise ValueError("无效请求长度")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or set(data) - {"request", "scenario", "engine"}:
                raise ValueError("无效请求字段")
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
            except (BrokenPipeError, ConnectionResetError):
                pass
        folder = uuid4().hex
        try:
            result = run_demo(**data, output=ROOT / "outputs/d-console" / folder,
                              emit=lambda item: send("trace", item))
            result["download_id"] = folder
            send("result", result)
        except Exception as exc:
            send("error", {"message": str(exc)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    print(f"ChainGuard D Mock 控制台：http://127.0.0.1:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
