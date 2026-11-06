"""控制台适配既有纵切；不实现第二套角色、检索或评分逻辑。"""
from __future__ import annotations

import json
from pathlib import Path

from src.trace import observe_events
from src.vertical_slice import run_vertical_slice


def run_local(request: str, *, output: Path, emit=None, publish=None) -> dict:
    history, draft = [], None

    def observe(item, value):
        nonlocal draft
        if emit:
            emit(item)
        if item["kind"] == "end" and item["node_id"] == "write":
            draft = value["draft"]
        if item["kind"] == "end" and item["node_id"] == "verify":
            snapshot = {"event_id": item["event_id"], "round": item["round"],
                        "scorecard": value, "draft": draft}
            history.append(snapshot)
            if publish:
                publish(snapshot)

    with observe_events(observe):
        result = run_vertical_slice(request, output=output)
    # 仅本机演示的评分/草稿快照；不塞进 trace_event 或正式四件交付物。
    (output / "review_history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"passed": result["scorecard"]["verdict"] == "pass", "run_id": result["run_id"],
            "scorecard": result["scorecard"], "history": history, "events": result["events"],
            "engine": "Mock LLM + 实际检索 / L1", "reason": "实际纵切完成；L2/L3 尚未接入。",
            "results": {"write": {"text": (output / "solution.md").read_text(encoding="utf-8")}}}
