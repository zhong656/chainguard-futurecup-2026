"""最小动态调度器：按拓扑层执行，记录失败、重试和降级决策。

调用方负责解释条件边与 LoopController 的修订轮次。本模块的超时采用守护线程：
超时后 run 可继续，但 Python 不能强制停止执行中的回调；信号量直到回调结束才释放。
不可信代码应交给独立进程或容器，不能交给此调度器直接运行。
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from src.trace import event


class NodeTimeout(TimeoutError):
    """节点执行或等待并发槽超时。"""


class RateLimitError(RuntimeError):
    """可重试的供应商限流。"""


class ServerError(RuntimeError):
    """可重试的供应商服务错误。"""


class BudgetExceeded(RuntimeError):
    """调用尝试次数用尽；本次 run 不再启动新节点。"""


def _number(value: Any, label: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} 必须是有限数值")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{label} 必须为{'非负' if allow_zero else '正'}数")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} 必须为正整数")
    return value


class Scheduler:
    def __init__(self, graph, policy: dict):
        if not isinstance(policy, dict):
            raise ValueError("scheduler policy 必须是对象")
        try:
            concurrency = policy["concurrency"]
            retry = policy["retry"]
            timeout = policy["timeout"]
            budget = policy["budget"]
            degradation = policy["degradation"]
            self.max_parallel_nodes = _positive_int(concurrency["max_parallel_nodes"], "max_parallel_nodes")
            self.queue_timeout_s = _number(concurrency["queue_timeout_s"], "queue_timeout_s")
            self.max_attempts = _positive_int(retry["max_attempts"], "max_attempts")
            if retry["backoff"] != "exponential":
                raise ValueError("retry.backoff 只支持 exponential")
            self.base_delay_s = _number(retry["base_delay_s"], "base_delay_s", allow_zero=True)
            self.max_delay_s = _number(retry["max_delay_s"], "max_delay_s", allow_zero=True)
            self.retry_on = frozenset(retry["retry_on"])
            self.default_timeout_s = _number(timeout["default_s"], "default_s")
            self.per_node_timeout = {
                key: _number(value, f"per_node.{key}") for key, value in timeout["per_node"].items()
            }
            self.calls_max = _positive_int(budget["calls_max"], "calls_max")
            self.degradation = dict(degradation)
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"scheduler policy 缺少必填配置：{exc}") from exc
        if self.max_delay_s < self.base_delay_s:
            raise ValueError("max_delay_s 不能小于 base_delay_s")
        if not self.retry_on <= {"timeout", "rate_limit", "server_error"}:
            raise ValueError("retry_on 含未知错误类型")
        for key in ("on_llm_failure", "on_tool_failure", "on_verifier_failure"):
            if self.degradation.get(key) not in {"skip_and_flag", "abort"}:
                raise ValueError(f"{key} 只支持 skip_and_flag 或 abort")
        self.graph = graph
        self._slots = threading.BoundedSemaphore(self.max_parallel_nodes)

    def _timeout_for(self, node_id: str) -> float:
        node = self.graph.nodes[node_id]
        return self.per_node_timeout.get(
            node_id, self.per_node_timeout.get(node.get("agent"), self.default_timeout_s)
        )

    @staticmethod
    def _error_kind(exc: Exception) -> str | None:
        if isinstance(exc, TimeoutError):
            return "timeout"
        if isinstance(exc, RateLimitError):
            return "rate_limit"
        if isinstance(exc, (ServerError, ConnectionError)):
            return "server_error"
        return None

    def _degradation_for(self, node_id: str) -> str:
        node = self.graph.nodes[node_id]
        if node.get("agent") == "verifier":
            return self.degradation["on_verifier_failure"]
        if node.get("type") == "agent":
            return self.degradation["on_llm_failure"]
        return self.degradation["on_tool_failure"]

    def _call(self, execute: Callable[[str], Any], node_id: str) -> Any:
        outcome: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                outcome.put((True, execute(node_id)))
            except Exception as exc:
                outcome.put((False, exc))
            finally:
                self._slots.release()

        try:
            threading.Thread(target=worker, daemon=True, name=f"scheduler-{node_id}").start()
        except Exception:
            self._slots.release()
            raise
        try:
            ok, value = outcome.get(timeout=self._timeout_for(node_id))
        except queue.Empty as exc:
            raise NodeTimeout(f"节点 {node_id} 执行超时") from exc
        if ok:
            return value
        raise value

    def run(
        self,
        execute,
        *,
        run_id: str,
        emit,
        active_nodes=None,
        completed_nodes=None,
        context: dict[str, Any] | None = None,
        should_run: Callable[[str, dict[str, Any]], bool] | None = None,
        event_fields: dict[str, Any] | None = None,
        budget_used: int = 0,
    ) -> dict:
        """执行当前轮的活动节点，并把结果写回 ``context``。

        ``active_nodes`` 让 LoopController 只重跑受影响的子图；
        ``completed_nodes`` 表示这些节点的结果来自上一轮，依赖检查仍可通过。
        ``should_run`` 用于 gate 后的条件分支，返回 False 的节点是有意跳过，
        不会被记录为降级。调用方因此不再需要复制按层遍历和重试逻辑。
        """
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id 不能为空")
        active = set(self.graph.nodes) if active_nodes is None else set(active_nodes)
        if not active <= self.graph.nodes.keys():
            raise ValueError(f"活动节点不存在：{sorted(active - self.graph.nodes.keys())}")
        state = context if context is not None else {}
        completed = set(state) if completed_nodes is None else set(completed_nodes)
        if not completed <= self.graph.nodes.keys():
            raise ValueError(f"已完成节点不存在：{sorted(completed - self.graph.nodes.keys())}")
        if not isinstance(budget_used, int) or isinstance(budget_used, bool) or not 0 <= budget_used <= self.calls_max:
            raise ValueError("budget_used 必须在 0 和 calls_max 之间")
        trace_id = run_id + "-trace"
        outputs: dict[str, Any] = {}
        node_status = {
            node_id: "pending" if node_id in active
            else "done" if node_id in completed else "skipped"
            for node_id in self.graph.nodes
        }
        degraded: list[str] = []
        calls_used = budget_used
        trace_fields = dict(event_fields or {})
        trace_round = trace_fields.pop("round", 0)

        def log(node_id: str, kind: str, **fields: Any) -> None:
            emit(event(trace_id, run_id, node_id, kind, round=trace_round,
                      **trace_fields, **fields))

        for layer in self.graph.layers:
            for node_id in layer:
                if node_id not in active:
                    continue
                if should_run is not None and not should_run(node_id, state):
                    node_status[node_id] = "skipped"
                    continue
                if any(node_status[parent] != "done" for parent in self.graph.dependencies[node_id]):
                    node_status[node_id] = "skipped"
                    degraded.append(node_id)
                    log(node_id, "degrade", reason="上游节点未完成")
                    continue
                for attempt in range(1, self.max_attempts + 1):
                    if calls_used >= self.calls_max:
                        log(node_id, "abort", reason="调用次数预算耗尽")
                        raise BudgetExceeded(f"调用预算耗尽：{calls_used}/{self.calls_max}")
                    if not self._slots.acquire(timeout=self.queue_timeout_s):
                        exc: Exception = NodeTimeout(f"节点 {node_id} 等待并发槽超时")
                    else:
                        calls_used += 1
                        node_status[node_id] = "running"
                        try:
                            log(node_id, "start", attempt=attempt,
                                input_value={"node": node_id, "round": trace_round})
                        except Exception:
                            self._slots.release()
                            raise
                        started = time.perf_counter()
                        try:
                            value = self._call(execute, node_id)
                        except Exception as error:
                            exc = error
                        else:
                            outputs[node_id] = value
                            state[node_id] = value
                            node_status[node_id] = "done"
                            log(node_id, "end", attempt=attempt,
                                duration_ms=int((time.perf_counter() - started) * 1000),
                                output_value=outputs[node_id])
                            break
                    node_status[node_id] = "failed"
                    kind = self._error_kind(exc)
                    log(node_id, "fail", attempt=attempt, error_class=type(exc).__name__,
                        reason=f"节点{kind or '不可重试'}失败")
                    if kind in self.retry_on and attempt < self.max_attempts:
                        log(node_id, "retry", attempt=attempt + 1, reason=kind)
                        time.sleep(min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1)))
                        continue
                    mode = self._degradation_for(node_id)
                    if mode == "abort":
                        log(node_id, "abort", reason="失败后按策略中止")
                        raise exc
                    node_status[node_id] = "skipped"
                    degraded.append(node_id)
                    log(node_id, "degrade", reason="重试耗尽或错误不可重试，跳过并标记")
                    break
        return {
            "run_id": run_id, "trace_id": trace_id, "outputs": outputs,
            "node_status": node_status, "degraded": degraded,
            "budget": {"calls_used": calls_used, "calls_max": self.calls_max},
        }
