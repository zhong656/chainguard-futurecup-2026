import hashlib
import json

import pytest

from scripts._schema import validator
from src.trace import read_trace, replay
from web.mock_runtime import run_demo


@pytest.mark.parametrize("scenario,passed,round", [
    ("normal", True, 1), ("numeric_conflict", True, 1),
    ("evidence_missing", False, 2), ("no_convergence", False, 2), ("timeout", False, 0),
])
def test_mock_scenarios_export_contracts(tmp_path, scenario, passed, round):
    result = run_demo(scenario=scenario, output=tmp_path)
    assert result["passed"] is passed and result["scorecard"]["round"] == round
    artifact = json.loads((tmp_path / "delivery_artifact.json").read_text(encoding="utf-8"))
    validator("delivery_artifact.schema.json").validate(artifact)
    events = read_trace(tmp_path / "trace.jsonl")
    assert len(replay(events)) == len(events)
    assert artifact["evidence_chain"] == json.loads((tmp_path / "evidence_chain.json").read_text(encoding="utf-8"))
    for file in artifact["manifest"]["files"]:
        data = (tmp_path / file["path"]).read_bytes()
        assert len(data) == file["bytes"] and hashlib.sha256(data).hexdigest() == file["sha256"]
    if scenario == "numeric_conflict":
        assert sum(e["node_id"] == "analyze" and e["kind"] == "start" for e in events) == 2
        assert sum(e["node_id"] == "outline" and e["kind"] == "start" for e in events) == 1
    if scenario == "timeout":
        assert any(e.get("error_class") == "TimeoutError" for e in events)


def test_real_langgraph_mock_roundtrip(tmp_path):
    pytest.importorskip("langgraph.graph")
    result = run_demo(scenario="numeric_conflict", engine="langgraph", output=tmp_path)
    assert result["passed"] and result["scorecard"]["round"] == 1


def test_trace_never_contains_request(tmp_path):
    request = "私密需求123ABC"
    run_demo(request, output=tmp_path)
    assert request not in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
