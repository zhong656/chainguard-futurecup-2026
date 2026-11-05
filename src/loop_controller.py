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
        if set(metrics) != set(weights) or "score" not in scorecard:
            raise ValueError("评分卡必须包含既定五维及总分")
        score = scorecard["score"]
        if not isfinite(score) or not all(isfinite(value) for value in metrics.values()):
            raise ValueError("评分必须为有限数")
        if scorecard.get("threshold", self.policy["pass_threshold"]) != self.policy["pass_threshold"]:
            raise ValueError("评分卡 threshold 与验证配置不一致")
        veto = self.policy["veto"]
        passed = (
            scorecard["verdict"] == "pass"
            and score >= self.policy["pass_threshold"]
            and all(value >= veto["metric_floor"] for value in metrics.values())
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
