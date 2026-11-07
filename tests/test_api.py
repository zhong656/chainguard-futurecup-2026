"""FastAPI contract checks for the background vertical slice adapter."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi", reason="API tests require the optional web runtime dependencies")
pytest.importorskip("httpx", reason="FastAPI TestClient requires httpx")

from fastapi.testclient import TestClient

from scripts._schema import validator
from src.main import app
from src import vertical_slice


def _start_run(client: TestClient) -> str:
    response = client.post("/runs", json={"request": "机器视觉质检"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "running"
    assert isinstance(body["run_id"], str) and body["run_id"]
    return body["run_id"]


def test_post_runs_returns_run_id():
    with TestClient(app) as client:
        _start_run(client)


def test_events_sse_contains_start_and_end():
    with TestClient(app) as client:
        run_id = _start_run(client)
        with client.stream("GET", f"/runs/{run_id}/events") as response:
            assert response.status_code == 200
            payload = "".join(response.iter_text())
    events = [json.loads(line[6:]) for line in payload.splitlines() if line.startswith("data: ")]
    kinds = {item["kind"] for item in events}
    assert {"start", "end"} <= kinds


def test_artifacts_are_a_valid_delivery_artifact():
    with TestClient(app) as client:
        run_id = _start_run(client)
        with client.stream("GET", f"/runs/{run_id}/events") as response:
            list(response.iter_text())
        response = client.get(f"/runs/{run_id}/artifacts")
        assert response.status_code == 200
        artifact = response.json()
        validator("delivery_artifact.schema.json").validate(artifact)


def test_commit_sha_has_schema_valid_sentinel_without_git(monkeypatch):
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.setattr(
        vertical_slice.subprocess,
        "check_output",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("no .git")),
    )
    assert vertical_slice._commit_sha() == "0000000"
