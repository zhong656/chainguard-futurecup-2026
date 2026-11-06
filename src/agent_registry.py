"""C：AgentRegistry（角色注册表）—— 6 份角色配置的唯一读取入口，支持热加载。

为什么需要它
------------
agents/*.yaml 是 6 个静态文本文件。A（架构与调度）要按 tier（模型档位）选模型，
D（编排与前端）要按 agent: 名字找角色，但两边都不该自己读文件、解析 YAML、
重复写校验。本模块把这件事收拢到一处：给一个名字，返回一份完整配置。

设计约定（都是为了让「改配置不改代码」真的成立）
------------------------------------------------
- 校验口径与 scripts/check_contracts.py 完全一致：结构说明书 + unknown_tools()
  + read_only 角色的工具必须全只读。不另立一套规则，避免「提交时放行、运行时拒绝」。
- 结构说明书直接从 contracts/agent_spec.schema.json 加载，不缓存副本。
  这份说明书内部没有跨文件 $ref（引用别的文件），用 jsonschema 自带校验器即可，
  因此不依赖 scripts/_schema.py —— C 的代码尽量不跨到别人的目录。
- 热加载用内容指纹（SHA256），不用文件修改时间：内容一变指纹必变，
  不受文件系统时间精度影响；6 个小文件，读取开销可忽略。
- get() 返回深拷贝：调用方改了自己手里那份，不会污染册子里的原版。
- agents_dir 可传入任意目录：自定义角色、测试用的坏配置都能加载，
  不必改动仓库里真实的 6 份文件。

职责边界
--------
- 只读取 agents/*.yaml，不写回
- 不做调度：tier 只如实返回，选哪一档模型是 A 的 Scheduler 的事
- 不改契约、不改别人的文件

对外接口（给 A / D 用）
----------------------
    from agent_registry import get_agent, default_registry
    role = get_agent("writer")           # 一份完整配置（dict）
    names = default_registry().names()   # 当前全部角色名
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]

# src/ 不是标准包（没有 __init__.py）。两种运行方式都要能找到 B 的工具注册表：
#   ① 把仓库根加进搜索路径，按 src.agent_registry 导入
#   ② 把 src/ 加进搜索路径，按顶层模块 agent_registry 导入
# 这里统一用第 ② 种的绝对导入，与 tests/test_agent_readonly.py 保持一致。
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.registry import TOOLS, unknown_tools  # noqa: E402

DEFAULT_AGENTS_DIR = ROOT / "agents"
AGENT_SPEC_SCHEMA = ROOT / "contracts" / "agent_spec.schema.json"

# jsonschema 的原生报错是英文。保留原文便于查资料，后面补一句中文，
# 让第一次接触项目的人也能立刻看懂是哪一格填错了。
_SCHEMA_HINTS = (
    ("is a required property", "缺少必填字段"),
    ("is not one of", "取值不在允许范围内"),
    ("is not of type", "字段类型不对"),
    ("Additional properties are not allowed", "出现了结构说明书里没有的字段"),
    ("does not match", "格式不符合规定"),
    ("is too short", "内容太短"),
)


def _explain(message: str) -> str:
    """给英文报错补一个中文括号说明；认不出来的原样返回。"""
    for needle, hint in _SCHEMA_HINTS:
        if needle in message:
            return f"{message}（{hint}）"
    return message


class AgentRegistryError(Exception):
    """角色注册表的基类异常：所有报错都能用这一个类型兜住。"""


class AgentSpecError(AgentRegistryError):
    """某份角色配置不合规：结构、工具名、只读声明或名字对不上。"""


class UnknownAgentError(AgentRegistryError):
    """按这个名字查不到角色（语义上等同于字典取不到键）。"""


def _fingerprint(files: list[Path]) -> str:
    """把目录下所有配置文件的名字和内容揉成一个指纹字符串。

    文件名也要参与计算：只改内容、增删文件、换文件名，三种情况都能被发现。
    """
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_one(path: Path, data: Any, validator: Draft202012Validator) -> dict:
    """校验单份配置；不合规就抛异常并说清是哪个文件、哪一格错了。"""
    if not isinstance(data, dict):
        raise AgentSpecError(
            f"{path.name}: 顶层必须是键值对象，实际是 {type(data).__name__}"
            "（空文件 / 整份只有注释都会这样）"
        )

    # ① 结构说明书：必填字段、字段类型、不许乱加字段
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise AgentSpecError(
            f"{path.name}: 结构说明书不通过 [{location}] {_explain(first.message)}"
        )

    # ② 文件名与 name 必须一致，否则以后改文件的人会找不到对应关系
    if data["name"] != path.stem:
        raise AgentSpecError(
            f"{path.name}: name={data['name']!r} 与文件名不一致（应叫 {path.stem}.yaml）"
        )

    # ③ 工具名必须在 B 的注册表里 —— 与 scripts/check_contracts.py 同一口径
    missing = unknown_tools(data["tools"])
    if missing:
        raise AgentSpecError(f"{path.name}: 未注册工具 {missing}（见 src/tools/registry.py）")

    # ④ read_only=true 的角色，不能配任何有副作用的工具 —— 同一口径
    if data["read_only"] is True:
        writable = [tool for tool in data["tools"] if not TOOLS[tool].read_only]
        if writable:
            raise AgentSpecError(f"{path.name}: 只读角色配了有副作用的工具 {writable}")

    return data


class AgentRegistry:
    """一本会自己翻新的花名册。

    agents_dir   角色配置目录，默认仓库 agents/
    schema_path  结构说明书路径，默认 contracts/agent_spec.schema.json
    auto_reload  每次查询前是否自动检查文件变化（关掉后只能手动 reload()）
    revision     第几次载入，从 1 开始；用来观测「确实重读了」
    """

    def __init__(
        self,
        agents_dir: str | Path | None = None,
        *,
        schema_path: str | Path | None = None,
        auto_reload: bool = True,
    ) -> None:
        self.agents_dir = Path(agents_dir) if agents_dir is not None else DEFAULT_AGENTS_DIR
        self.schema_path = Path(schema_path) if schema_path is not None else AGENT_SPEC_SCHEMA
        self.auto_reload = auto_reload
        self._validator = Draft202012Validator(
            json.loads(self.schema_path.read_text(encoding="utf-8"))
        )
        self._roles: dict[str, dict] = {}
        self._digest = ""
        self.revision = 0
        self.reload()

    def _files(self) -> list[Path]:
        if not self.agents_dir.is_dir():
            raise AgentRegistryError(f"角色配置目录不存在：{self.agents_dir}")
        return sorted(self.agents_dir.glob("*.yaml"))

    def reload(self) -> AgentRegistry:
        """全量重读并校验。

        任何一份不合规就抛异常，已加载的内容不被替换，不留半本册子。
        注意这不是「静默沿用旧配置」：文件只要还是坏的，后续每次查询都会
        重新尝试加载并继续报错（fail loud，响亮地失败）；修好文件后自动恢复，
        无需重建实例。
        """
        files = self._files()
        digest = _fingerprint(files)
        roles: dict[str, dict] = {}
        for path in files:
            try:
                # utf-8-sig 能自动吃掉 Windows 记事本写出的隐藏字节（BOM）
                raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            except (yaml.YAMLError, OSError) as exc:
                raise AgentSpecError(f"{path.name}: 读取或解析失败：{exc}") from exc
            role = _validate_one(path, raw, self._validator)
            if role["name"] in roles:
                raise AgentSpecError(f"{path.name}: 角色名重复：{role['name']}")
            roles[role["name"]] = role

        # 先全部校验通过，再一次性替换：坏配置不会把好册子弄成半截状态
        self._roles = roles
        self._digest = digest
        self.revision += 1
        return self

    def _ensure_fresh(self) -> None:
        if self.auto_reload and _fingerprint(self._files()) != self._digest:
            self.reload()

    def get(self, name: str) -> dict:
        """按名字取一份完整配置，返回复印件。查不到抛 UnknownAgentError。"""
        self._ensure_fresh()
        if name not in self._roles:
            raise UnknownAgentError(
                f"未注册角色：{name!r}；现有：{', '.join(sorted(self._roles)) or '（空）'}"
            )
        return copy.deepcopy(self._roles[name])

    def names(self) -> list[str]:
        """当前全部角色名，按字母序（稳定输出，方便做对比和打印）。"""
        self._ensure_fresh()
        return sorted(self._roles)

    def all(self) -> dict[str, dict]:
        """整本册子的复印件，键是角色名。"""
        self._ensure_fresh()
        return copy.deepcopy(self._roles)

    def __contains__(self, name: object) -> bool:
        self._ensure_fresh()
        return name in self._roles

    def __len__(self) -> int:
        self._ensure_fresh()
        return len(self._roles)


_DEFAULT_REGISTRY: AgentRegistry | None = None


def default_registry() -> AgentRegistry:
    """进程内共享一本册子（第一次用到才创建）。

    共享实例 + 自动热加载，正好实现「改 YAML 不重启生效」：
    A / D 不必各自建实例，改完配置下一次查询就是新值。
    """
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = AgentRegistry()
    return _DEFAULT_REGISTRY


def get_agent(name: str) -> dict:
    """最简接口：给名字，给配置。A 的调度器与 D 的编译器可以直接用。"""
    return default_registry().get(name)
