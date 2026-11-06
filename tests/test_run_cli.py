"""阶段 0 验收：计划指定的模块命令能独立完成离线纵切。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts._schema import validator

ROOT = Path(__file__).resolve().parents[1]


def test_module_cli_exports_verified_delivery(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "src.run", "--request", "产线质检", "--output", str(tmp_path)],
        cwd=ROOT, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"[PASS]" in result.stdout
    assert {"solution.md", "evidence_chain.json", "scorecard.json", "trace.jsonl"} <= {
        path.name for path in tmp_path.iterdir()
    }
    artifact = json.loads((tmp_path / "delivery_artifact.json").read_text(encoding="utf-8"))
    validator("delivery_artifact.schema.json").validate(artifact)
    assert artifact["scorecard"]["verdict"] == "pass"


def test_module_cli_returns_failure_for_empty_request(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "src.run", "--request", "", "--output", str(tmp_path)],
        cwd=ROOT, capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert b"[FAIL]" in result.stderr
    assert not (tmp_path / "delivery_artifact.json").exists()
