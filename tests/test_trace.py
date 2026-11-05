import json

import pytest

from src.trace import event, read_trace, replay, write_trace


def test_trace_hashes_private_inputs_and_replays(tmp_path):
    events = [event("trace", "run", "write", kind, input_value="私密需求和提示词") for kind in ["start", "end"]]
    path = tmp_path / "trace.jsonl"
    write_trace(path, events)
    assert "私密" not in path.read_text(encoding="utf-8")
    loaded = read_trace(path)
    assert loaded == events
    assert replay(loaded)[-1]["nodes"] == {"write": "done"}
    assert replay(loaded) == replay(loaded)


@pytest.mark.parametrize("mutation", ["duplicate", "trace_id", "timestamp", "extra"])
def test_trace_rejects_corruption(tmp_path, mutation):
    data = [event("trace", "run", "write", "start"), event("trace", "run", "write", "end")]
    if mutation == "duplicate":
        data[1]["event_id"] = data[0]["event_id"]
    elif mutation == "trace_id":
        data[1]["trace_id"] = "another"
    elif mutation == "timestamp":
        data[1]["ts"] = "wrong"
    else:
        data[1]["prompt"] = "禁止落盘的原文"
    path = tmp_path / "bad.jsonl"
    path.write_text("\n".join(map(json.dumps, data)), encoding="utf-8")
    with pytest.raises(ValueError, match="第 2 行"):
        read_trace(path)
