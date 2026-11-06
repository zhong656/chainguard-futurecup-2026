"""FastAPI adapter for the existing offline vertical slice."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import Condition, Lock, Thread
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.trace import observe_events
from src.vertical_slice import ROOT, run_vertical_slice


class RunRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)


@dataclass
class RunRecord:
    run_id: str
    request: str
    output: Path
    status: str = "running"
    events: list[dict] = field(default_factory=list)
    artifact: dict | None = None
    error: str | None = None
    condition: Condition = field(default_factory=Condition, repr=False)

    def add_event(self, item: dict) -> None:
        with self.condition:
            self.events.append(item)
            self.condition.notify_all()

    def finish(self, *, status: str, artifact: dict | None = None, error: str | None = None) -> None:
        with self.condition:
            self.status = status
            self.artifact = artifact
            self.error = error
            self.condition.notify_all()


app = FastAPI(title="ChainGuard API", version="0.1.0")
_runs: dict[str, RunRecord] = {}
_runs_lock = Lock()


def _get_run(run_id: str) -> RunRecord:
    with _runs_lock:
        record = _runs.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run 不存在")
    return record


def _run_worker(record: RunRecord) -> None:
    def publish(item: dict, _value) -> None:
        record.add_event(item)

    try:
        with observe_events(publish):
            result = run_vertical_slice(
                record.request,
                output=record.output,
                run_id=record.run_id,
            )
        record.finish(status="passed", artifact=result["artifact"])
    except Exception as exc:  # the run remains queryable and its trace is preserved when available
        record.finish(status="failed", error=str(exc))


@app.post("/runs")
def create_run(payload: RunRequest) -> dict:
    run_id = uuid4().hex
    record = RunRecord(run_id=run_id, request=payload.request, output=ROOT / "outputs" / "api" / run_id)
    with _runs_lock:
        _runs[run_id] = record
    Thread(target=_run_worker, args=(record,), name=f"run-{run_id}", daemon=True).start()
    return {"run_id": run_id, "status": "running"}


@app.get("/runs/{run_id}/events")
def stream_events(run_id: str) -> StreamingResponse:
    record = _get_run(run_id)

    def generate():
        index = 0
        while True:
            with record.condition:
                while index >= len(record.events) and record.status == "running":
                    record.condition.wait(timeout=0.25)
                batch = record.events[index:]
                index = len(record.events)
                done = record.status != "running" and index >= len(record.events)
            for item in batch:
                yield "event: trace\ndata: " + json.dumps(item, ensure_ascii=False) + "\n\n"
            if done:
                return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/runs/{run_id}/artifacts")
def get_artifacts(run_id: str) -> dict:
    record = _get_run(run_id)
    if record.status == "running":
        raise HTTPException(status_code=409, detail="run 仍在执行")
    if record.status != "passed" or record.artifact is None:
        raise HTTPException(status_code=500, detail=record.error or "run 未生成交付物")
    return record.artifact
