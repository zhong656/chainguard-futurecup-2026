"""C 的 agent_spec.read_only 验收：角色声明必须与工具注册表一致。

跨文件约束（tools ⊆ registry 且只读角色的工具都 read_only）最终由 A 加进
scripts/check_contracts.py；这里先给一份可独立运行的自检，避免等脚本落地前
出现「角色写了只读、工具却能写文件」的逻辑漏洞。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tools.registry import TOOLS, unknown_tools  # noqa: E402

READ_ONLY_ROLES = {"planner", "researcher", "verifier", "reviewer"}
WRITABLE_ROLES = {"analyst", "writer"}


@pytest.fixture(scope="module")
def roles() -> dict:
    return {
        p.stem: yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in sorted((ROOT / "agents").glob("*.yaml"))
    }


def test_six_roles_all_declare_boolean_read_only(roles) -> None:
    assert set(roles) == READ_ONLY_ROLES | WRITABLE_ROLES
    for name, role in roles.items():
        assert isinstance(role.get("read_only"), bool), f"{name} 未声明布尔 read_only"


def test_read_only_roles_use_only_read_only_tools(roles) -> None:
    for name in READ_ONLY_ROLES:
        role = roles[name]
        assert role["read_only"] is True
        assert not unknown_tools(role["tools"]), f"{name} 引用了未注册工具"
        bad = [t for t in role["tools"] if not TOOLS[t].read_only]
        assert not bad, f"{name} 声明只读却调用了有副作用的工具：{bad}"


def test_read_only_roles_never_use_python_sandbox(roles) -> None:
    for name in READ_ONLY_ROLES:
        assert "python_sandbox" not in roles[name]["tools"]


def test_writable_roles_are_explicitly_false(roles) -> None:
    for name in WRITABLE_ROLES:
        assert roles[name]["read_only"] is False


def test_schema_enforces_required_boolean_read_only() -> None:
    schema = json.loads((ROOT / "contracts/agent_spec.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    good = json.loads((ROOT / "contracts/examples/agent_spec.good.json").read_text(encoding="utf-8"))

    assert not list(validator.iter_errors(good)), "正例必须通过 schema"
    assert list(validator.iter_errors({**good, "read_only": "yes"})), "read_only 写成字符串必须被拒"
    missing = {k: v for k, v in good.items() if k != "read_only"}
    assert list(validator.iter_errors(missing)), "漏填 read_only 必须被拒（不允许缺省推断）"
