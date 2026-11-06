"""Scheduler 的故障注入验收。"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.scheduler import BudgetExceeded, Scheduler

ROOT = Path(__file__).resolve().parents[1]


def graph(*nodes):
    return SimpleNamespace(
        nodes={node: {"id": node, "type": "agent", "agent": "writer"} for node in nodes},
        dependencies={node: (nodes[index - 1],) if index else () for index, node in enumerate(nodes)},
        layers=tuple((node,) for node in nodes),
    )


def policy(**overrides):
    config = yaml.safe_load((ROOT / "configs/scheduler.yaml").read_text(encoding="utf-8"))
    for section, values in overrides.items():
        config[section].update(values)
    return config


def test_timeout_is_recorded_and_run_does_not_hang():
    events = []
    scheduler = Scheduler(graph("slow", "after"), policy(timeout={"default_s": 0.01}))

    def execute(node_id):
        if node_id == "slow":
            time.sleep(0.2)
        return node_id

    started = time.monotonic()
    result = scheduler.run(execute, run_id="timeout", emit=events.append)
    assert time.monotonic() - started < 0.2
    assert result["node_status"] == {"slow": "skipped", "after": "skipped"}
    assert any(item["kind"] == "fail" and item["error_class"] == "NodeTimeout" for item in events)
    assert any(item["kind"] == "degrade" for item in events)


def test_retry_exhaustion_degrades_after_n_attempts():
    events = []
    scheduler = Scheduler(graph("flaky"), policy(retry={"max_attempts": 3, "base_delay_s": 0}))
    calls = 0

    def execute(_node_id):
        nonlocal calls
        calls += 1
        raise ConnectionError("permanent failure")

    result = scheduler.run(execute, run_id="retry", emit=events.append)
    assert calls == 3
    assert result["budget"]["calls_used"] == 3
    assert result["node_status"]["flaky"] == "skipped"
    assert [item["attempt"] for item in events if item["kind"] == "retry"] == [2, 3]
    assert events[-1]["kind"] == "degrade"


def test_budget_is_checked_before_each_attempt():
    events = []
    scheduler = Scheduler(graph("first", "second"), policy(budget={"calls_max": 1}))
    with pytest.raises(BudgetExceeded, match="预算耗尽"):
        scheduler.run(lambda node_id: node_id, run_id="budget", emit=events.append)
    assert [item["node_id"] for item in events if item["kind"] == "abort"] == ["second"]
