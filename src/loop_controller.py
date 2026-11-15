"""D：只消费工作流/评分卡/验证配置；不调用模型或重算 C 的评分。"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class LoopDecision:
    action: str
    round: int
    targets: tuple[str, ...] = ()
    rerun_nodes: tuple[str, ...] = ()
    reason: str = ""


# 允许出现在 metrics 里、但不参与加权的额外维度（白名单）
ALLOWED_EXTRA_METRICS: frozenset[str] = frozenset({"cross_check"})


class LoopController:
    """一次运行一个实例；初稿为 round=0，最多追加三轮修订。"""

    def __init__(self, graph, policy: dict):
        if not graph.loop:
            raise ValueError("工作流没有 loop 配置")
        if graph.loop["max_rounds"] != 3 or graph.loop["stop_if_no_gain_rounds"] != 2:
            raise ValueError("循环护栏固定为三轮上限、两轮无提升停止")
        self.graph, self.policy = graph, policy
        self.round = 0
        self.best_score = -1.0
        self.no_gain = 0

    def decide(self, scorecard: dict) -> LoopDecision:
        # 格式校验包括 source_id 的本地 $ref，禁止远端解析。
        from scripts._schema import validator
        validator("scorecard.schema.json").validate(scorecard)
        if scorecard.get("round", self.round) != self.round:
            raise ValueError("评分卡 round 与当前轮次不一致")
        weights = self.policy["weights"]
        metrics = scorecard["metrics"]
        # 五维必须全在；**额外维度只允许白名单里的**（L3 的 cross_check）。
        # 用白名单而不是"放宽为超集"：放宽会让任何拼错的维度名被静默忽略，
        # 白名单只对明确声明的维度开口子。
        extra = set(metrics) - set(weights)
        if set(weights) - set(metrics) or (extra - ALLOWED_EXTRA_METRICS) or "score" not in scorecard:
            raise ValueError(
                "评分卡必须包含既定五维及总分"
                + (f"（额外维度仅允许 {sorted(ALLOWED_EXTRA_METRICS)}，实际多出 {sorted(extra)}）"
                   if extra - ALLOWED_EXTRA_METRICS else "")
            )
        score = scorecard["score"]
        if not isfinite(score) or not all(isfinite(value) for value in metrics.values()):
            raise ValueError("评分必须为有限数")
        if scorecard.get("threshold", self.policy["pass_threshold"]) != self.policy["pass_threshold"]:
            raise ValueError("评分卡 threshold 与验证配置不一致")
        veto = self.policy["veto"]
        passed = (
            scorecard["verdict"] == "pass"
            and score >= self.policy["pass_threshold"]
            # 地板只作用于**加权维度**：cross_check 这类观测维度不参与，
        # 否则 cross_check=0.0 会把本来 pass 的一轮判成需要 revise。
        and all(metrics[k] >= veto["metric_floor"] for k in weights)
            and not any(issue["severity"] == "blocker" for issue in scorecard["issues"])
        )
        if passed:
            return LoopDecision("pass", self.round, reason="评分通过且无一票否决")
        if scorecard["verdict"] == "abort":
            return LoopDecision("abort", self.round, reason="验证器要求中止")
        no_gain = self.no_gain + 1 if score <= self.best_score else 0
        if no_gain >= self.graph.loop["stop_if_no_gain_rounds"]:
            return LoopDecision("abort", self.round, reason="连续两轮无提升")
        if self.round >= self.graph.loop["max_rounds"]:
            return LoopDecision("abort", self.round, reason="已达三轮修订上限")
        targets = {issue["target_node"] for issue in scorecard["issues"]}
        targets = targets or {self.graph.loop["to"]}
        # 只接受能够重新流经 verify 的修订落点；gate/review 等不能修复草稿。
        eligible, pending = set(), ["verify"] if "verify" in self.graph.nodes else []
        while pending:
            node = pending.pop()
            if node not in eligible:
                eligible.add(node)
                pending.extend(self.graph.dependencies[node])
        if not targets <= eligible - {"verify"}:
            raise ValueError("target_node 不存在或不在 verify 的修订前驱中")
        rerun, pending = set(), list(targets)
        while pending:
            node = pending.pop()
            if node not in rerun:
                rerun.add(node)
                if node != "verify":
                    pending.extend(self.graph.successors[node])
        ordered = tuple(node for layer in self.graph.layers for node in layer if node in rerun)
        # 多个问题一起处理；公共下游只重算一次，未受影响分支保留。
        self.no_gain, self.best_score = no_gain, max(self.best_score, score)
        self.round += 1
        return LoopDecision("revise", self.round, tuple(sorted(targets)), ordered, "按问题节点定向回退")
