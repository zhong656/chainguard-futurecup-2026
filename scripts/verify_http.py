"""离线验证：把 FastAPI 应用起成真实 HTTP 服务，跑通三个接口。

为什么需要它
------------
`tests/test_api.py` 用的是 `TestClient`（进程内 ASGI 调用）。它能证明路由和契约对，
但证明不了**真的能作为服务起来**：端口绑定、SSE 分块推送、并发线程写同一个 run 记录，
这些只有走真实 socket 才暴露。

本机没有 Docker，所以用它替代 `docker compose up` 的一部分验证：
容器验证 = 依赖安装 + 进程启动 + 端口可用；本脚本覆盖后两项。

用法：
    python scripts/verify_http.py
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from src.main import app  # noqa: E402


class _Server(uvicorn.Server):
    """在后台线程跑服务，主线程用来发请求。"""

    def install_signal_handlers(self) -> None:  # 线程里不能装信号处理
        return


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = _Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    if not server.started:
        print("[FAIL] 服务未能在 30s 内启动")
        return 1

    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(timeout=180) as client:
            resp = client.post(f"{base}/runs", json={"request": "用机器视觉升级精密零件产线质检"})
            resp.raise_for_status()
            run_id = resp.json()["run_id"]
            print(f"[OK] POST /runs -> run_id={run_id}")

            kinds: list[str] = []
            with client.stream("GET", f"{base}/runs/{run_id}/events") as stream:
                stream.raise_for_status()
                for line in stream.iter_lines():
                    if line.startswith("data:"):
                        payload = json.loads(line[5:].strip())
                        kinds.append(payload.get("kind", "?"))
            print(f"[OK] SSE /events -> {len(kinds)} 条事件，类型 {sorted(set(kinds))}")
            assert "start" in kinds and "end" in kinds, "SSE 缺少 start/end"

            art = client.get(f"{base}/runs/{run_id}/artifacts").json()
            files = [f["path"] for f in art["manifest"]["files"]]
            print(f"[OK] GET /artifacts -> manifest {len(files)} 项：{files}")
            assert "rounds.json" in files and any(p.startswith("charts/") for p in files), "交付物缺 rounds 或图表"
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] HTTP 验证失败：{exc}")
        return 1
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    print("[PASS] 真实 HTTP 三接口通过（容器内构建仍需 Docker 环境验证）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
