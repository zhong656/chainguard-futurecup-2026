"""C：AgentRegistry 验收 —— 读取、热加载、坏配置拦截。

测试用的角色配置一律写在 pytest 的临时目录里，不改仓库中真实的 6 份 YAML。
校验口径刻意与 scripts/check_contracts.py 对齐，避免「静态检查放行、运行时拒绝」。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_registry import (  # noqa: E402
    AgentRegistry,
    AgentSpecError,
    UnknownAgentError,
    default_registry,
    get_agent,
)

# 结构说明书里 6 个必填格子，一份不多一份不少。
MINIMAL = {
    "name": "probe",
    "role": "测试用角色",
    "tier": "small",
    "tools": ["knowledge_retrieve"],
    "output_schema": "Probe",
    "read_only": True,
}

EXPECTED_NAMES = ["analyst", "planner", "researcher", "reviewer", "verifier", "writer"]


def write_role(directory: Path, data: dict, filename: str | None = None) -> Path:
    """往临时目录写一份配置，返回文件路径。"""
    path = directory / f"{filename or data['name']}.yaml"
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------- 正常组


def test_loads_all_six_roles_from_repo():
    registry = AgentRegistry()
    assert registry.names() == EXPECTED_NAMES
    assert len(registry) == 6
    assert "writer" in registry
    assert "nobody" not in registry


def test_get_returns_full_config():
    role = AgentRegistry().get("planner")
    for key in (
        "name", "role", "tier", "tools", "output_schema", "read_only",
        "timeout_s", "temperature", "retry",
    ):
        assert key in role, f"缺少字段 {key}"
    assert role["name"] == "planner"
    assert role["read_only"] is True


def test_tiers_match_llm_routing():
    """6 份 YAML 的 tier 必须与 A 的 configs/llm.yaml routing 逐项一致。

    这里只是读取 A 的配置做验收，不修改 A 的任何文件。
    """
    routing = yaml.safe_load(
        (ROOT / "configs" / "llm.yaml").read_text(encoding="utf-8")
    )["routing"]
    roles = AgentRegistry().all()
    assert set(routing) == set(roles), "角色集合与路由表不一致"
    for name, tier in routing.items():
        assert roles[name]["tier"] == tier, f"{name} 的档位与路由表冲突"


def test_get_returns_independent_copy():
    """借出去的是复印件：改了它，册子里的原版不受影响。"""
    registry = AgentRegistry()
    borrowed = registry.get("writer")
    borrowed["tools"].append("not_a_tool")
    borrowed["temperature"] = 9.9
    fresh = registry.get("writer")
    assert "not_a_tool" not in fresh["tools"]
    assert fresh["temperature"] != 9.9


def test_unknown_agent_raises_clear_error():
    with pytest.raises(UnknownAgentError) as exc:
        AgentRegistry().get("nobody")
    assert "nobody" in str(exc.value)
    assert "writer" in str(exc.value), "报错里应列出可用角色，方便定位拼写错误"


def test_default_registry_is_shared_and_get_agent_works():
    assert default_registry() is default_registry()
    assert get_agent("researcher")["tier"] == "small"
    assert get_agent("writer")["tier"] == "strong"


# -------------------------------------------------------------- 热加载组


def test_hot_reload_picks_up_changed_tier(tmp_path):
    """改 YAML 不重启、不重建实例，下一次查询就是新值。"""
    write_role(tmp_path, dict(MINIMAL))
    registry = AgentRegistry(tmp_path)
    assert registry.get("probe")["tier"] == "small"
    before = registry.revision

    write_role(tmp_path, dict(MINIMAL, tier="strong"))
    assert registry.get("probe")["tier"] == "strong"
    assert registry.revision == before + 1, "应只重读一次"


def test_hot_reload_detects_new_role(tmp_path):
    write_role(tmp_path, dict(MINIMAL))
    registry = AgentRegistry(tmp_path)
    assert registry.names() == ["probe"]

    write_role(tmp_path, dict(MINIMAL, name="probe2"))
    assert registry.names() == ["probe", "probe2"]
    assert registry.get("probe2")["name"] == "probe2"


def test_hot_reload_detects_removed_role(tmp_path):
    write_role(tmp_path, dict(MINIMAL))
    write_role(tmp_path, dict(MINIMAL, name="probe2"))
    registry = AgentRegistry(tmp_path)
    assert len(registry) == 2

    (tmp_path / "probe2.yaml").unlink()
    assert len(registry) == 1
    with pytest.raises(UnknownAgentError):
        registry.get("probe2")


def test_auto_reload_can_be_turned_off(tmp_path):
    write_role(tmp_path, dict(MINIMAL))
    registry = AgentRegistry(tmp_path, auto_reload=False)
    assert registry.get("probe")["tier"] == "small"

    write_role(tmp_path, dict(MINIMAL, tier="strong"))
    assert registry.get("probe")["tier"] == "small", "关掉自动刷新后应仍是旧值"
    registry.reload()
    assert registry.get("probe")["tier"] == "strong", "手动 reload 后应读到新值"


def test_bad_edit_fails_loudly_and_recovers(tmp_path):
    """改坏配置要响亮报错，不能静默沿用旧值；改好后自动恢复，无需重启。"""
    write_role(tmp_path, dict(MINIMAL))
    registry = AgentRegistry(tmp_path)

    write_role(tmp_path, dict(MINIMAL, tools=["not_a_tool"]))
    with pytest.raises(AgentSpecError, match="未注册工具"):
        registry.get("probe")

    write_role(tmp_path, dict(MINIMAL, tier="strong"))
    assert registry.get("probe")["tier"] == "strong"


# -------------------------------------------------------------- 拦错组


def test_rejects_missing_read_only(tmp_path):
    """read_only 是 #27 定下的必填字段，运行时也必须拦住漏填。"""
    data = dict(MINIMAL)
    del data["read_only"]
    write_role(tmp_path, data)
    with pytest.raises(AgentSpecError, match="read_only"):
        AgentRegistry(tmp_path)


def test_schema_error_has_chinese_hint(tmp_path):
    """报错要让人看得懂：英文原文保留，后面补中文说明。"""
    data = dict(MINIMAL)
    del data["read_only"]
    write_role(tmp_path, data)
    with pytest.raises(AgentSpecError) as exc:
        AgentRegistry(tmp_path)
    assert "缺少必填字段" in str(exc.value)
    assert "read_only" in str(exc.value)


def test_rejects_unknown_tool(tmp_path):
    write_role(tmp_path, dict(MINIMAL, tools=["not_a_tool"]))
    with pytest.raises(AgentSpecError, match="未注册工具"):
        AgentRegistry(tmp_path)


def test_rejects_writable_tool_on_read_only_role(tmp_path):
    """python_sandbox 已注册，但它是有副作用的工具，只读角色不能用。"""
    write_role(tmp_path, dict(MINIMAL, tools=["python_sandbox"], read_only=True))
    with pytest.raises(AgentSpecError, match="有副作用"):
        AgentRegistry(tmp_path)


def test_allows_writable_tool_when_not_read_only(tmp_path):
    """同一工具，显式声明 read_only=false 就合法 —— 正反对照。"""
    write_role(tmp_path, dict(MINIMAL, tools=["python_sandbox"], read_only=False))
    registry = AgentRegistry(tmp_path)
    assert registry.get("probe")["tools"] == ["python_sandbox"]


def test_rejects_name_mismatch(tmp_path):
    write_role(tmp_path, dict(MINIMAL), filename="wrong")
    with pytest.raises(AgentSpecError, match="与文件名不一致"):
        AgentRegistry(tmp_path)


def test_rejects_empty_file(tmp_path):
    (tmp_path / "empty.yaml").write_text("# 整份只有注释\n", encoding="utf-8")
    with pytest.raises(AgentSpecError, match="顶层"):
        AgentRegistry(tmp_path)


def test_rejects_broken_yaml(tmp_path):
    (tmp_path / "broken.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(AgentSpecError, match="读取或解析失败"):
        AgentRegistry(tmp_path)
