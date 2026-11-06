"""Scheduler 与纵切的故障注入接线验收。"""

from __future__ import annotations

import pytest

from src.trace import read_trace
from src.vertical_slice import VerticalSliceError, run_vertical_slice


def test_timeout_injection_keeps_fail_retry_degrade_trace(tmp_path):
    with pytest.raises(VerticalSliceError, match="已保留 trace.jsonl"):
        run_vertical_slice(
            "机器视觉",
            output=tmp_path,
            inject_fault="timeout",
            fault_node="retrieve",
        )

    kinds = {item["kind"] for item in read_trace(tmp_path / "trace.jsonl")}
    assert {"fail", "retry", "degrade"} <= kinds
