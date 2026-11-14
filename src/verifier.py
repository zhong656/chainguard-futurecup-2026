"""C：L2 独立验证器 —— 判逻辑自洽，补上 L1 恒给 1.0 的 logic 维度。

职责边界（对应 contracts/ 与 configs/）：
    - 独立：verifier 与 writer 的 temperature 必须不同（agents/*.yaml 已写死），
      且 verifier 必须 read_only；构造实例时强校验，配置被改坏会立刻报错。
    - 不调模型：默认判定函数是确定性规则，Mock（假数据）阶段无 Key、可复现；
      judge_fn 可注入，A 将来接真实模型时不必重写本模块。
    - 不另立规则：权重 / 0.85 阈值 / 一票否决全部读 configs/verifier.yaml；
      最终输出是 L1 评分卡合并后的同一张卡，可直接喂 LoopController。
    - 不改 L1：L1 负责引用 / 数值 / 章节 / Schema，本模块只负责 logic 一维。

三条 L2 规则（均为 warning，不新增一票否决条件）：
    LOGIC_UNSUPPORTED    结论句没有可回溯的引用       -> write
    LOGIC_JUMP           结论与所引证据毫无词汇重合   -> write
    LOGIC_CONTRADICTION  同一指标在不同章节数字打架   -> fanout

对外接口：
    judge(draft, evidence=None, judge_fn=None)  -> L2Judgement（logic 分 + 问题列表）
    verify(draft, evidence=None, judge_fn=None) -> 完整 ScoreCard（L1 + L2 合并）
    Verifier(...)                               -> 可注入角色配置的实例，便于测试

judge_fn 签名：(draft: dict, index: EvidenceIndex) -> (logic: float, issues: list[dict])
    issues 每项须符合 scorecard.schema.json 的 issues[] 形状。
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for _path in (str(ROOT), str(SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# src/ 不是标准包，沿用 dag_compiler.py 的双写法；scripts/ 只导入、不修改。
try:
    from src.rule_checker import EvidenceIndex, check as l1_check
    from src.agent_registry import default_registry
except ImportError:  # 直接把 src/ 加进搜索路径时
    from rule_checker import EvidenceIndex, check as l1_check
    from agent_registry import default_registry

from scripts._schema import validator  # noqa: E402

CONFIG = ROOT / "configs" / "verifier.yaml"
SCORECARD_SCHEMA = "scorecard.schema.json"

CONCLUSION_RE = re.compile(r"因此|所以|综上|可见|表明|证明|建议|据此|得出结论|推断")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 指标词 + 至多 14 个非句读字符 + 数字 + 可选单位；只用于跨段数字打架检测。
METRIC_RE = re.compile(
    r"(回收期|工期|周期|漏检率|过杀率|良率|准确率|投入|成本|预算|产能|节拍)"
    r"[^。；，\n]{0,14}?(\d+(?:\.\d+)?)\s*(万元|%|个月|周|天|条|倍|元)?"
)

TARGET_NODE = {
    "LOGIC_UNSUPPORTED": "write",
    "LOGIC_JUMP": "write",
    "LOGIC_CONTRADICTION": "fanout",
}
PENALTY = {
    "LOGIC_UNSUPPORTED": 0.30,
    "LOGIC_JUMP": 0.25,
    "LOGIC_CONTRADICTION": 0.30,
}


class VerifierConfigError(RuntimeError):
    """角色配置破坏了「独立验证」的前提。"""


@dataclass(frozen=True)
class L2Judgement:
    """L2 的判定结果；不是评分卡，交给 merge 合成后才出口。"""

    logic: float
    issues: tuple[dict, ...]
    verifier_temperature: float
    writer_temperature: float


def _policy() -> dict:
    return (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {})["scorecard"]


DEFAULT_LAYERS: dict[str, bool] = {"rules": True, "llm_judge": True, "cross_check": False}


def _layers(config_path: Path | None = None) -> dict[str, bool]:
    """读取三层验证开关；缺省按 DEFAULT_LAYERS，避免"没写=关掉"这种危险默认。"""
    raw = yaml.safe_load((config_path or CONFIG).read_text(encoding="utf-8")) or {}
    declared = raw.get("layers") or {}
    layers = dict(DEFAULT_LAYERS)
    for key, value in declared.items():
        if key in layers:
            layers[key] = bool(value)
    return layers


def check_layers(layers: dict) -> None:
    """校验开关组合是否可实现。

    两条必须挡住的情况：
    1. `rules: false` —— L1 是确定性兜底，其余四个维度都依赖它；关掉后评分卡
       只能凭空填分，比不开验证更危险。
    2. `cross_check: true` —— 2026-11-14 起已实现（双路检索比对），不再拦截。
    """
    if not layers.get("rules", True):
        raise VerifierConfigError(
            "layers.rules 不能关闭：L1 是确定性兜底，关闭后 citation/consistency/"
            "coverage/format 四个维度失去数据来源，评分卡只能凭空填分"
        )
    # L3（cross_check）已于 2026-11-14 实现，见 src/cross_check.py；不再拦截


def _bigrams(text: str) -> set[str]:
    """中文二字词集合：不装分词库，也能判断两段文字有没有实质重合。"""
    chars = "".join(CJK_RE.findall(text))
    return {chars[i : i + 2] for i in range(len(chars) - 1)}


def _issue(section: str, reason: str, suggestion: str, rule_id: str) -> dict:
    return {
        "section": section,
        "reason": reason,
        "suggestion": suggestion,
        "target_node": TARGET_NODE[rule_id],
        "rule_id": rule_id,
        "severity": "warning",
    }


def _contradiction(sections: list[dict]) -> tuple[str, str] | None:
    """同一（指标, 单位）在不同段落出现互不相交的数字集合 -> 视为自相矛盾。"""
    groups: dict[tuple[str, str], dict[int, set[str]]] = {}
    for pos, section in enumerate(sections, start=1):
        content = str(section.get("content") or "")
        for match in METRIC_RE.finditer(content):
            key = (match.group(1), match.group(3) or "")
            groups.setdefault(key, {}).setdefault(pos, set()).add(match.group(2))
    for (metric, unit), by_pos in groups.items():
        if len(by_pos) < 2:
            continue
        sets = list(by_pos.values())
        for i, left in enumerate(sets):
            for right in sets[i + 1 :]:
                if not (left & right):
                    label = f"{metric}{('（' + unit + '）') if unit else ''}"
                    detail = "、".join("/".join(sorted(s)) for s in sets)
                    return label, detail
    return None


def _mock_judge(draft: dict, index: EvidenceIndex) -> tuple[float, list[dict]]:
    """确定性判定：不联网、不用 Key、同样输入永远同样输出。"""
    sections = list(draft.get("sections") or [])
    issues: list[dict] = []
    penalty = 0.0

    for pos, section in enumerate(sections, start=1):
        title = str(section.get("title") or f"第 {pos} 段")
        label = f"{pos}. {title}"
        content = str(section.get("content") or "")
        if not CONCLUSION_RE.search(content):
            continue
        sids = [str(sid) for sid in (section.get("citations") or [])]
        usable = [sid for sid in sids if index.has(sid)]

        if not usable:
            issues.append(
                _issue(
                    label,
                    "结论句没有可回溯的引用支撑，属于逻辑跳跃",
                    "补引能支撑该结论的 source_id，或改写为对证据的客观复述",
                    "LOGIC_UNSUPPORTED",
                )
            )
            penalty += PENALTY["LOGIC_UNSUPPORTED"]
            continue

        evidence_text = "\n".join(index.text(sid) for sid in usable)
        # 证据链只有 id、占位语料过短时跳过，避免把「没有原文」误判成「逻辑不通」。
        if len("".join(CJK_RE.findall(evidence_text))) < 12:
            continue
        if not (_bigrams(content) & _bigrams(evidence_text)):
            issues.append(
                _issue(
                    label,
                    "结论与所引证据没有任何实质词汇重合，引用可能挂错",
                    "核对 source_id 与段落内容，改引真正支撑该结论的语料",
                    "LOGIC_JUMP",
                )
            )
            penalty += PENALTY["LOGIC_JUMP"]

    clash = _contradiction(sections)
    if clash:
        label, detail = clash
        issues.append(
            _issue(
                "跨章节一致性",
                f"同一指标 {label} 在不同章节写成 {detail}，结论互相打架",
                "回到分析分支统一口径后重算，再重写受影响章节",
                "LOGIC_CONTRADICTION",
            )
        )
        penalty += PENALTY["LOGIC_CONTRADICTION"]

    return round(max(0.0, 1.0 - penalty), 3), issues


def _merge(l1_card: dict, judgement: L2Judgement, policy: dict,
           cross: dict | None = None) -> dict:
    """把 L2 判定（以及可选的 L3 双路比对结果）并进 L1 评分卡。

    L3 只**追加维度与 issue**，不参与加权（`weights` 里没有 cross_check 这个键，
    所以逐项求和时自然忽略它）——它衡量的是"支撑强度"，不是"质量分"。
    """
    weights = policy["weights"]
    metrics = dict(l1_card["metrics"])
    metrics["logic"] = judgement.logic
    issues = list(l1_card["issues"]) + list(judgement.issues)
    if cross is not None:
        metrics["cross_check"] = cross["agreement"]
        issues.extend(cross["issues"])
    score = round(sum(weights[key] * metrics[key] for key in weights), 3)
    threshold = float(policy["pass_threshold"])
    veto = policy["veto"]
    failed = (
        score < threshold
        or min(metrics[k] for k in weights) < float(veto["metric_floor"])
        or (bool(veto["blocker_issue"]) and any(i["severity"] == "blocker" for i in issues))
    )
    card = {
        "run_id": l1_card["run_id"],
        "round": l1_card.get("round", 0),
        "score": score,
        "threshold": threshold,
        "metrics": metrics,
        "issues": issues,
        "verdict": "fail" if failed else "pass",
    }
    validator(SCORECARD_SCHEMA).validate(card)
    return card


class Verifier:
    """一次运行一个实例；默认配置来自 AgentRegistry（角色注册表）。"""

    def __init__(self, verifier_spec=None, writer_spec=None, registry=None, layers=None) -> None:
        reg = registry if registry is not None else default_registry()
        self.verifier_spec = dict(
            verifier_spec if verifier_spec is not None else reg.get("verifier")
        )
        self.writer_spec = dict(writer_spec if writer_spec is not None else reg.get("writer"))
        self.layers = dict(DEFAULT_LAYERS if layers is None else layers)
        check_layers(self.layers)
        self._assert_independent()

    def _assert_independent(self) -> None:
        try:
            v_temp = float(self.verifier_spec["temperature"])
            w_temp = float(self.writer_spec["temperature"])
        except (KeyError, TypeError, ValueError) as exc:
            raise VerifierConfigError("verifier / writer 缺少 temperature 配置") from exc
        if v_temp == w_temp:
            raise VerifierConfigError(
                f"独立验证失效：verifier 与 writer 的 temperature 同为 {v_temp}，"
                "判卷人与写稿人同源，无法避免同源偏差"
            )
        if self.verifier_spec.get("read_only") is not True:
            raise VerifierConfigError("verifier 必须 read_only=true：只打分，不改草稿")
        self.verifier_temperature = v_temp
        self.writer_temperature = w_temp

    def judge(self, draft: dict, evidence=None, judge_fn=None) -> L2Judgement:
        index = EvidenceIndex(evidence)
        fn = judge_fn or _mock_judge
        logic, issues = fn(draft, index)
        return L2Judgement(
            logic=round(min(max(float(logic), 0.0), 1.0), 3),
            issues=tuple(issues),
            verifier_temperature=self.verifier_temperature,
            writer_temperature=self.writer_temperature,
        )

    def verify(self, draft: dict, evidence=None, judge_fn=None) -> dict:
        """返回可直接喂 LoopController 的完整评分卡。

        L1 恒开（`check_layers` 保证）；`llm_judge` 关闭时只返回 L1 卡，
        logic 保持 1.0 —— 没做 L2 就承认没做，不臆造分数。
        """
        l1_card = l1_check(draft, evidence)

        cross = None
        if self.layers.get("cross_check", False):
            # L3：对每条引用做双路复核。失败不抛异常——L3 是增强信号，
            # 不能因为它挂掉就让整次验证失败（那是把附录当主程序的错）。
            from src import cross_check as _cc

            try:
                report = _cc.cross_check(draft)
                cross = report.to_dict()
            except Exception as exc:  # noqa: BLE001
                cross = {"checked": 0, "confirmed": 0, "agreement": 1.0,
                         "issues": [{"code": "CROSS_CHECK_SKIPPED", "severity": "minor",
                                     "target_node": "write",
                                     "message": f"L3 未能执行：{type(exc).__name__}"}]}

        if not self.layers.get("llm_judge", True):
            if cross is None:
                return l1_card
            # 只开 L1+L3：仍然要把 cross_check 维度并进去
            merged = dict(l1_card)
            merged["metrics"] = {**l1_card["metrics"], "cross_check": cross["agreement"]}
            merged["issues"] = list(l1_card["issues"]) + cross["issues"]
            validator(SCORECARD_SCHEMA).validate(merged)
            return merged

        judgement = self.judge(draft, evidence, judge_fn)
        return _merge(l1_card, judgement, _policy(), cross)


_default: Verifier | None = None


def default_verifier() -> Verifier:
    global _default
    if _default is None:
        _default = Verifier(layers=_layers())
    return _default


def judge(draft: dict, evidence=None, judge_fn=None) -> L2Judgement:
    return default_verifier().judge(draft, evidence, judge_fn)


def verify(draft: dict, evidence=None, judge_fn=None) -> dict:
    return default_verifier().verify(draft, evidence, judge_fn)
