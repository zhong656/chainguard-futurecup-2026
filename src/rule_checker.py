"""C：L1 规则验证器 —— 引用 / 数值 / 章节 / Schema。

`check(draft, evidence)` 返回一个严格符合 `scorecard.schema.json` 的评分卡，
可直接交给 D 的 `LoopController.decide()`，不需要中间适配层。

职责边界（对应 contracts/ 与 configs/）：
    - 不做检索：证据来自 B 的 `src/evidence.py` / `src/knowledge_hub.py`
    - 不定义权重：维度、阈值、一票否决一律读 `configs/verifier.yaml`
    - 不判逻辑：L1 只做确定性检查，logic 维度留给 L2 独立 Verifier Agent
    - 不拦引用缺失：Draft 契约故意允许 `citations` 为空/缺失，坏稿样本才造得出来；
      缺引用由本模块报 `CITATION_MISSING`，而不是在 Schema 里强制

evidence 支持的形态（方便 Mock 与真实链路共用同一个检查器）：
    - `EvidencePool` 实例（有 `refs_for()`；用公开 API 回溯，不碰私有属性）
    - `dict[str, str]`：source_id → 原文
    - `retrieval_result` dict（含 items）或 `list[dict]`（含 source_id / text|snippet）
    - `list[str]`：evidence_chain，只有 id 可见，数值检查自动跳过
    - `None`：空证据池，所有引用都判为不可回溯
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._schema import validator  # noqa: E402

CONFIG = ROOT / "configs" / "verifier.yaml"
DRAFT_SCHEMA = "draft.schema.json"
SCORECARD_SCHEMA = "scorecard.schema.json"

# verifier.yaml 的 rules 段目前仍是注释占位；A 解冻后自动生效，代码不用改。
# 这里只作为兜底，避免规则验证器在配置落地前静默跳过章节检查。
DEFAULT_REQUIRED_SECTIONS = (
    "现状痛点",
    "技术选型",
    "数据方案",
    "实施阶段",
    "成本与ROI",
    "风险与合规",
)

NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
SOURCE_ID_RE = re.compile(r"^[a-z]+:[A-Za-z0-9_-]+$")

# target_node 必须落在 verify 的修订前驱里（见 workflows/industry_solution.yaml），
# 否则 D 的 LoopController 会拒绝回退。
TARGET_NODE = {
    "SCHEMA_INVALID": "write",
    "CITATION_MISSING": "write",
    "CITATION_UNKNOWN": "write",
    "MISSING_SECTION": "write",
    "NUMERIC_MISMATCH": "fanout",
}


def _load_config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def _policy() -> dict:
    return _load_config()["scorecard"]


def required_sections() -> tuple[str, ...]:
    """必需章节优先取 verifier.yaml 的 rules.sections.required。"""
    rules = _load_config().get("rules") or {}
    sections = (rules.get("sections") or {}).get("required")
    return tuple(sections) if sections else DEFAULT_REQUIRED_SECTIONS


class EvidenceIndex:
    """把多种证据形态归一化成「能否回溯 + 原文」。"""

    def __init__(self, evidence) -> None:
        self._pool = None
        self._texts: dict[str, str] = {}
        if evidence is None:
            return
        if hasattr(evidence, "refs_for"):
            self._pool = evidence
            return
        if isinstance(evidence, dict) and "items" in evidence:
            items = evidence["items"]
        elif isinstance(evidence, dict):
            items = [{"source_id": key, "text": value} for key, value in evidence.items()]
        elif isinstance(evidence, (list, tuple, set)):
            items = [entry if isinstance(entry, dict) else {"source_id": entry} for entry in evidence]
        else:
            raise TypeError(f"不支持的 evidence 形态：{type(evidence).__name__}")
        for item in items:
            sid = str(item.get("source_id", ""))
            if not sid:
                continue
            text = str(item.get("text") or item.get("snippet") or "")
            self._texts[sid] = (self._texts.get(sid, "") + "\n" + text).strip()

    def has(self, source_id: str) -> bool:
        if self._pool is not None:
            try:
                self._pool.refs_for(source_id)
                return True
            except Exception:  # EvidenceError / 未知 source_id
                return False
        return source_id in self._texts

    def text(self, source_id: str) -> str:
        if self._pool is not None:
            try:
                return "\n".join(str(ref.get("text", "")) for ref in self._pool.refs_for(source_id))
            except Exception:
                return ""
        return self._texts.get(source_id, "")


def _issue(
    section: str,
    reason: str,
    suggestion: str,
    rule_id: str,
    severity: str,
    source_id: str | None = None,
) -> dict:
    issue = {
        "section": section,
        "reason": reason,
        "suggestion": suggestion,
        "target_node": TARGET_NODE[rule_id],
        "rule_id": rule_id,
        "severity": severity,
    }
    # scorecard.issues[].source_id 有 $ref 正则；假引用可能不合法，不能硬塞。
    if source_id and SOURCE_ID_RE.match(source_id):
        issue["source_id"] = source_id
    return issue


def _numbers(text: str) -> set[str]:
    return set(NUMBER_RE.findall(text))


def _round_of(draft: dict) -> int:
    try:
        value = int(draft.get("round", 0))
    except (TypeError, ValueError):
        value = 0
    return min(max(value, 0), 3)


def check(draft: dict, evidence=None) -> dict:
    """验证一份 Draft，返回可直接喂给 LoopController 的 ScoreCard。

    metric 口径（与 configs/verifier.yaml 的注释一致）：
        citation     = 引用完整且可回溯的段落 / 总段落
        consistency  = 数值可在证据中找到的段落 / 参与数值比对的段落
                       （证据本身不含数字时跳过，避免占位语料造成误报）
        coverage     = 必需章节命中数 / 必需章节总数
        logic        = 1.0（L1 不判逻辑，由 L2 独立 Verifier 负责）
        format       = Draft Schema 合规为 1.0，否则 0.0
    """
    policy = _policy()
    weights = policy["weights"]
    index = EvidenceIndex(evidence)
    sections = draft.get("sections") or []
    issues: list[dict] = []

    # ---- 规则 4：Schema 合规 ---- #
    schema_errors = list(validator(DRAFT_SCHEMA).iter_errors(draft))
    format_score = 1.0 if not schema_errors else 0.0
    if schema_errors:
        first = schema_errors[0]
        issues.append(
            _issue(
                "<root>",
                f"Draft 不符合 draft.schema.json：{first.message}",
                "按契约补齐字段后重跑验证（形状问题不靠规则兜底）",
                "SCHEMA_INVALID",
                "blocker",
            )
        )

    # ---- 规则 1/2：引用真实性 + 数值一致性 ---- #
    citation_ok = 0
    numeric_total = 0
    numeric_ok = 0
    for pos, section in enumerate(sections, start=1):
        title = str(section.get("title") or f"第 {pos} 段")
        label = f"{pos}. {title}"
        sids = [str(sid) for sid in (section.get("citations") or [])]

        if not sids:
            issues.append(
                _issue(
                    label,
                    "该段没有回填任何 source_id，结论不可核验",
                    "从证据池补充至少 1 条 source_id 并重写该段",
                    "CITATION_MISSING",
                    "blocker",
                )
            )
            continue

        unknown = [sid for sid in sids if not index.has(sid)]
        if unknown:
            for sid in unknown:
                issues.append(
                    _issue(
                        label,
                        f"引用了证据池中无法回溯的 source_id：{sid}",
                        "删除该引用或先由检索侧把该语料并入证据池",
                        "CITATION_UNKNOWN",
                        "blocker",
                        sid,
                    )
                )
            continue

        citation_ok += 1
        content = str(section.get("content") or "")
        wanted = _numbers(content)
        if not wanted:
            continue
        evidence_text = "\n".join(index.text(sid) for sid in sids)
        available = _numbers(evidence_text)
        if not available:
            # 占位语料常不含数字；没有比对基准就不判，避免假阳性。
            continue
        numeric_total += 1
        missing = sorted(wanted - available)
        if missing:
            issues.append(
                _issue(
                    label,
                    f"段落数值 {'、'.join(missing)} 无法在引用证据中找到",
                    "核对参数表后修正数字，或改引包含该数值的语料",
                    "NUMERIC_MISMATCH",
                    "warning",
                )
            )
        else:
            numeric_ok += 1

    # ---- 规则 3：章节完整性 ---- #
    required = required_sections()
    titles = {str(s.get("title") or "").strip() for s in sections}
    missing_sections = [name for name in required if name not in titles]
    for name in missing_sections:
        issues.append(
            _issue(
                name,
                "缺少模板要求的必需章节",
                f"补写「{name}」章节并附可回溯引用",
                "MISSING_SECTION",
                "warning",
            )
        )

    raw_metrics = {
        "citation": citation_ok / len(sections) if sections else 0.0,
        "consistency": numeric_ok / numeric_total if numeric_total else 1.0,
        "coverage": (len(required) - len(missing_sections)) / len(required) if required else 1.0,
        "logic": 1.0,
        "format": format_score,
    }
    # 维度集合必须与权重表完全一致（LoopController 会校验），新增维度默认满分。
    metrics = {key: round(float(raw_metrics.get(key, 1.0)), 3) for key in weights}
    score = round(sum(weights[key] * metrics[key] for key in weights), 3)
    threshold = float(policy["pass_threshold"])
    veto = policy["veto"]
    failed = (
        score < threshold
        or min(metrics.values()) < float(veto["metric_floor"])
        or (bool(veto["blocker_issue"]) and any(i["severity"] == "blocker" for i in issues))
    )

    card = {
        "run_id": str(draft.get("run_id", "unknown")),
        "round": _round_of(draft),
        "score": score,
        "threshold": threshold,
        "metrics": metrics,
        "issues": issues,
        "verdict": "fail" if failed else "pass",
    }
    # 出口自检：D 的 LoopController 会再校验一次，这里先挡住不合格输出。
    validator(SCORECARD_SCHEMA).validate(card)
    return card
