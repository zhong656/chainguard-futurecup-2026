"""用 Edge 的 CDP 接口截"运行中"的控制台画面（方案书 §6 用图）。

为什么不用 `msedge --screenshot`：那只截静态首屏，拿不到"点下运行后"的状态——
而官方要的正是「平台界面 / Agent 编排 / 调度执行 / 验证与反馈」的运行画面。

做法：Edge 开 `--remote-debugging-port`，用 DevTools 协议
点按钮 → 等事件流跑起来 → 截整页。

用法：
    python scripts/capture_console.py --url http://127.0.0.1:8766/ --out <目录>
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
import urllib.request
from pathlib import Path

import websocket

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def _edge() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("[FAIL] 找不到 msedge.exe")


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.seq = 0

    def call(self, method: str, **params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.seq:
                return msg.get("result", {})

    def eval(self, expression: str):
        return self.call("Runtime.evaluate", expression=expression, returnByValue=True,
                         awaitPromise=True)

    def shot(self, path: Path):
        data = self.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
        path.write_bytes(base64.b64decode(data["data"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766/")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9222)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [_edge(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--remote-debugging-port={args.port}",
         "--window-size=1680,1200", "--user-data-dir=" + str(Path(args.out) / "_edge_profile"),
         args.url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ws_url = ""
        for _ in range(30):
            time.sleep(1)
            try:
                pages = json.loads(urllib.request.urlopen(
                    f"http://127.0.0.1:{args.port}/json", timeout=3).read())
                for page in pages:
                    if page.get("type") == "page" and "127.0.0.1" in page.get("url", ""):
                        ws_url = page["webSocketDebuggerUrl"]
                        break
                if ws_url:
                    break
            except Exception:
                continue
        if not ws_url:
            raise SystemExit("[FAIL] 连不上 Edge 调试端口")

        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        time.sleep(2)

        # 1) 首屏
        cdp.shot(args.out / "01-控制台首屏.png")

        # 2) 点"运行工作流"，等事件流
        clicked = cdp.eval("""
            (() => {
              const btns = [...document.querySelectorAll('button')];
              const t = btns.find(b => b.textContent.includes('运行工作流'));
              if (t) { t.click(); return 'clicked'; }
              return 'not-found';
            })()
        """)
        print("  点击运行:", clicked.get("result", {}).get("value"))
        time.sleep(14)
        cdp.shot(args.out / "02-运行中.png")

        # 3) 等收敛，截完成态
        time.sleep(16)
        cdp.shot(args.out / "03-运行完成.png")

        state = cdp.eval("document.body.innerText.slice(0, 400)")
        print("  页面文本片段:", (state.get("result", {}).get("value") or "")[:200].replace("\n", " | "))
    finally:
        proc.terminate()

    for p in sorted(args.out.glob("*.png")):
        if not p.name.startswith("_"):
            print(f"  {p.name}  {p.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
