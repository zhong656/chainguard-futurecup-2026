"""#43：实际纵切 → SSE → 落盘 Trace，逐条一致；回放不执行工作流。"""
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

import pytest

from src.trace import digest, event, observe_events, read_trace, replay
from web import demo_server
from web.local_runtime import run_local


def test_real_console_matches_persisted_trace_and_keeps_failed_round(tmp_path):
    streamed, reviews = [], []
    result = run_local("机器视觉质检", output=tmp_path, emit=streamed.append, publish=reviews.append)
    stored = read_trace(tmp_path / "trace.jsonl")
    assert streamed == stored == result["events"]
    assert reviews == result["history"] == json.loads((tmp_path / "review_history.json").read_text(encoding="utf-8"))
    assert [r["scorecard"]["verdict"] for r in reviews] == ["fail", "pass"]
    assert reviews[0]["scorecard"]["issues"][0]["target_node"] == "write"
    by_id = {item["event_id"]: item for item in stored}
    for review in reviews:
        assert by_id[review["event_id"]]["output_digest"] == digest(review["scorecard"])
    starts = [e["node_id"] for e in stored if e["kind"] == "start" and e["round"] == 1]
    assert starts == ["write", "verify", "gate", "review", "snap"]
    assert "机器视觉质检" not in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    artifact = json.loads((tmp_path / "delivery_artifact.json").read_text(encoding="utf-8"))
    assert artifact["trace_bundle"] == stored
    assert result["passed"] and result["engine"] == "Mock LLM + 实际检索 / L1"


def test_http_stream_is_identical_to_download(tmp_path, monkeypatch):
    # 配置仍来自真实仓库；仅把本次输出重定向到临时目录。
    import web.local_runtime as runtime
    original = runtime.run_local

    def local(request, *, output, **kwargs):
        return original(request, output=tmp_path / "outputs/d-console" / output.name, **kwargs)

    monkeypatch.setattr(demo_server, "run_local", local)
    monkeypatch.setattr(demo_server, "ROOT", tmp_path)
    service = demo_server.ThreadingHTTPServer(("127.0.0.1", 0), demo_server.Handler)
    thread = Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{service.server_port}"
        request = Request(base + "/api/run-real", data=json.dumps({"request":"机器视觉质检"}).encode(),
                          headers={"Content-Type":"application/json"})
        with urlopen(request, timeout=15) as response:
            chunks = response.read().decode().strip().split("\n\n")
        frames = [(c.splitlines()[0][7:], json.loads(c.split("data: ", 1)[1])) for c in chunks]
        result = frames[-1][1]
        assert frames[-1][0] == "result" and result["passed"]
        with urlopen(base + f"/download?run={result['download_id']}&file=trace.jsonl") as response:
            stored = [json.loads(line) for line in response.read().decode().splitlines()]
        assert [v for kind, v in frames if kind == "trace"] == stored == result["events"]
        assert [v["scorecard"]["verdict"] for kind, v in frames if kind == "review"] == ["fail","pass"]
    finally:
        service.shutdown()
        service.server_close()
        thread.join()


def test_observer_cannot_mutate_trace_or_leak_to_another_context():
    captured = []

    def observe(item, value):
        captured.append(item["event_id"])
        item["kind"] = "abort"
        value["private"] = "modified"

    value = {"private":"original"}
    with observe_events(observe):
        actual = event("trace", "run", "write", "end", output_value=value)
        with ThreadPoolExecutor() as executor:
            other = executor.submit(event, "other", "other", "plan", "start").result()
        assert other["event_id"] not in captured
    outside = event("trace", "run", "snap", "end")
    assert captured == [actual["event_id"]] and outside["event_id"] not in captured
    assert actual["kind"] == "end" and value == {"private":"original"}
    assert actual["output_digest"] == digest(value)
    with pytest.raises(RuntimeError, match="reset"):
        with observe_events(observe):
            raise RuntimeError("reset")
    event("trace", "run", "snap", "end")  # 异常退出也必须恢复上下文。


def test_replay_order_and_all_event_states_match_browser():
    kinds = ["start","end","fail","retry","degrade","revise","abort","checkpoint"]
    events = [event("trace","run",f"n{i}",kind) for i, kind in enumerate(kinds)]
    for i, item in enumerate(events):
        item["ts"] = f"2026-11-06T00:00:00.{i:06d}Z"
    events[0]["ts"] = "2026-11-06T08:00:00.000000+08:00"
    # 时间相同则保留文件顺序；不能按 event_id 重新打乱。
    events[-1]["ts"] = events[-2]["ts"]
    shuffled = list(reversed(events[:-2])) + events[-2:]
    frames = replay(shuffled)
    assert [f["event"] for f in frames] == events
    expected = {"n0":"running","n1":"done","n2":"failed","n3":"retrying",
                "n4":"degraded","n5":"revising","n6":"failed"}
    assert frames[-1]["nodes"] == expected
    node = shutil.which("node")
    if node is None:
        pytest.skip("浏览器纯函数验收需 Node；Python 重放部分已验证")
    root = Path(__file__).resolve().parents[1]
    script = "const t=require('./web/trace_view.js');let x='';process.stdin.on('data',s=>x+=s);process.stdin.on('end',()=>{const a=t.ordered(JSON.parse(x));console.log(JSON.stringify({events:a,nodes:t.reduce(a)}));});"
    result = subprocess.run([node,"-e",script], input=json.dumps(shuffled), text=True,
                            capture_output=True, check=True, cwd=root)
    browser = json.loads(result.stdout)
    assert browser == {"events":events,"nodes":expected}
