"""D：Trace 契约结构、哈希与只读重放；A 的日志策略可从此接口接入。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts/trace_event.schema.json").read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)


def _validate(data):
    VALIDATOR.validate(data)
    # CI 只装 jsonschema，未必有其可选 RFC3339 插件；日期检查不依赖该插件。
    timestamp = data["ts"]
    if not re.fullmatch(r"\d{4}-\d\d-\d\d[Tt]\d\d:\d\d:\d\d(?:\.\d+)?(?:[Zz]|[+-]\d\d:\d\d)", timestamp):
        raise ValueError("ts 必须为带时区的 RFC3339 时间")
    datetime.fromisoformat(timestamp.replace("z", "+00:00").replace("Z", "+00:00"))


def digest(value) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def event(trace_id, run_id, node_id, kind, *, round=0, input_value=None, output_value=None, **fields):
    """敏感输入只以 SHA256 落盘，不保存提示词、需求或模型原文。"""
    data = {
        "event_id": uuid4().hex, "trace_id": trace_id, "run_id": run_id,
        "ts": datetime.now(timezone.utc).isoformat(), "node_id": node_id,
        "kind": kind, "round": round, **fields,
    }
    if input_value is not None:
        data["input_digest"] = digest(input_value)
    if output_value is not None:
        data["output_digest"] = digest(output_value)
    _validate(data)
    return data


def write_trace(path: str | Path, events: list[dict]) -> None:
    for item in events:
        _validate(item)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events), encoding="utf-8")


def read_trace(path: str | Path) -> list[dict]:
    events, ids, trace_id = [], set(), None
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            _validate(item)
            if item["event_id"] in ids:
                raise ValueError("重复 event_id")
            if trace_id is not None and item["trace_id"] != trace_id:
                raise ValueError("一份 Trace 混入不同 trace_id")
        except Exception as exc:
            raise ValueError(f"Trace 第 {line_number} 行无效：{exc}") from exc
        trace_id = item["trace_id"]
        ids.add(item["event_id"])
        events.append(item)
    return events


def replay(events: list[dict]) -> list[dict]:
    """按文件顺序生成审计帧；不执行工具，也不把 Trace 当 checkpoint 续跑。"""
    states, frames = {}, []
    kinds = {"start": "running", "end": "done", "fail": "failed", "abort": "failed"}
    for item in events:
        _validate(item)
        if item["kind"] in kinds:
            states[item["node_id"]] = kinds[item["kind"]]
        frames.append({"event": dict(item), "nodes": dict(states)})
    return frames
