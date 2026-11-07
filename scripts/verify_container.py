"""在 CI 里验证容器镜像：构建 → 起容器 → 打接口 → 断言交付物 → 收尾。

为什么放在 CI 而不是本地
------------------------
Docker 需要管理员权限 + WSL2/Hyper-V + 重启，不是每台开发机都能装。
GitHub 的 ubuntu runner **自带 Docker**，把镜像验证放进 CI，
就不存在"只有某个人能验"的问题——每次 PR 都会真构建一次。

断言口径与 `scripts/verify_http.py` 一致：
    POST /runs → SSE 含 start/end → artifacts 必须含 rounds.json 与 charts/*.svg
额外的容器相关断言：
    GIT_COMMIT 环境变量必须生效（容器里没有 .git，读不到就会退化成 unknown）
"""

from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"


def wait_ready(client: httpx.Client, timeout: float = 90) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if client.get(f"{BASE}/docs", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit("[FAIL] 容器 90s 内未就绪（/docs 不可访问）")


def main() -> int:
    with httpx.Client(timeout=180) as client:
        wait_ready(client)
        print("[OK] /docs 可访问，容器已就绪")

        resp = client.post(f"{BASE}/runs", json={"request": "用机器视觉升级精密零件产线质检"})
        resp.raise_for_status()
        run_id = resp.json()["run_id"]
        print(f"[OK] POST /runs -> {run_id}")

        kinds: list[str] = []
        with client.stream("GET", f"{BASE}/runs/{run_id}/events") as stream:
            stream.raise_for_status()
            for line in stream.iter_lines():
                if line.startswith("data:"):
                    kinds.append(json.loads(line[5:].strip()).get("kind", "?"))
        print(f"[OK] SSE -> {len(kinds)} 条事件 {sorted(set(kinds))}")
        assert "start" in kinds and "end" in kinds, "SSE 缺 start/end"

        artifact = client.get(f"{BASE}/runs/{run_id}/artifacts").json()
        files = [f["path"] for f in artifact["manifest"]["files"]]
        print(f"[OK] artifacts -> {files}")
        assert "rounds.json" in files, "交付物缺 rounds.json"
        assert any(p.startswith("charts/") for p in files), "交付物缺图表"

        commit = artifact["manifest"]["commit_sha"]
        print(f"[OK] commit_sha={commit}")
        assert commit != "unknown", "容器里 commit_sha 退化为 unknown，GIT_COMMIT 未生效"

    print("[PASS] 容器镜像可用：构建、启动、三接口、交付物、commit_sha 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
