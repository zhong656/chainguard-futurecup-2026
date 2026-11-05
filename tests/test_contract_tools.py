"""Cross-file tool checks must fail before an invalid agent reaches runtime."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import check_contracts  # noqa: E402
from _schema import load_all  # noqa: E402


def check_agent(monkeypatch, tmp_path, tools: list[str], read_only: bool) -> list[dict]:
    agent = yaml.safe_load((ROOT / "agents/planner.yaml").read_text(encoding="utf-8"))
    agent["tools"] = tools
    agent["read_only"] = read_only
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "planner.yaml").write_text(yaml.safe_dump(agent), encoding="utf-8")

    monkeypatch.setattr(check_contracts, "ROOT", tmp_path)
    check_contracts.results.clear()
    check_contracts.check_configs({"docs": load_all()})
    return list(check_contracts.results)


def test_unknown_tool_fails_consistency_check(monkeypatch, tmp_path) -> None:
    results = check_agent(monkeypatch, tmp_path, ["knowledge_retrieve", "missing_tool"], True)
    assert any(r["level"] == "ERROR" and "未注册工具" in r["name"] for r in results)


def test_read_only_agent_cannot_use_writable_tool(monkeypatch, tmp_path) -> None:
    results = check_agent(monkeypatch, tmp_path, ["python_sandbox"], True)
    assert any(r["level"] == "ERROR" and "只读工具越权" in r["name"] for r in results)


def test_unpinned_dependency_fails_consistency_check(monkeypatch, tmp_path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    monkeypatch.setattr(check_contracts, "ROOT", tmp_path)
    check_contracts.results.clear()
    check_contracts.check_requirements()
    assert any(r["level"] == "ERROR" and "依赖锁定" in r["name"] for r in check_contracts.results)
