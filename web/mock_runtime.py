"""D 的离线纵切演示；角色/评分为显式 Mock 桩，检索消费 B 的已合并接口。

python -m web.mock_runtime --engine langgraph --output outputs/d-demo
运行时导出四件交付物及通过契约验证的 delivery_artifact.json。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from threading import Lock
from uuid import uuid4

import yaml

from scripts._schema import validator
from src.dag_compiler import ROOT, compile_langgraph, compile_workflow
from src.knowledge_hub import available_sources, retrieve
from src.loop_controller import LoopController
from src.trace import digest, event, write_trace

SECTIONS = ("现状痛点", "技术选型", "数据方案", "实施阶段", "成本与ROI", "风险与合规")
SCENARIOS = ("normal", "numeric_conflict", "evidence_missing", "timeout", "no_convergence")


def _commit_sha() -> str:
    """在非 git 目录（评审解压后的包）里也能给出合法的 commit_sha。"""
    import os

    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            encoding="utf-8", errors="replace",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "0000000"


def run_demo(request="用机器视觉升级精密零件产线质检", *, scenario="normal", engine="python", output=None, emit=None):
    if not isinstance(request, str) or not request.strip() or len(request) > 4000:
        raise ValueError("需求须为 1–4000 字的非空文本")
    if scenario not in SCENARIOS or engine not in {"python", "langgraph"}:
        raise ValueError("未知场景或执行引擎")
    graph = compile_workflow(ROOT / "workflows/industry_solution.yaml")
    policy = yaml.safe_load((ROOT / "configs/verifier.yaml").read_text(encoding="utf-8"))["scorecard"]
    controller = LoopController(graph, policy)
    run_id = "mock-" + uuid4().hex[:12]
    state = {"request": request, "run_id": run_id, "trace_id": run_id + "-trace", "round": 0, "results": {}}
    events, active, reason = [], set(graph.nodes), ""
    trace_lock = Lock()
    config_version = digest({"nodes": graph.nodes, "loop": graph.loop, "policy": policy})

    def record(item):
        with trace_lock:
            item["config_version"] = config_version
            events.append(item)
            if emit is not None:
                emit(item)

    def writer(current):
        if scenario == "timeout":
            raise TimeoutError("Mock 超时")
        refs = current["results"]["retrieve"]["items"]
        omit = scenario in {"no_convergence", "evidence_missing"} or current["round"] == 0
        citation = "" if omit or not refs else " [" + refs[0]["source_id"] + "]"
        text = "# 产业技术方案（Mock 演示，非正式交付）\n\n"
        for title in SECTIONS:
            text += f"## {title}\n\n基于离线占位语料安排小规模试点，验收参数和成本由用户补充。{citation}\n\n"
        return {"text": text}

    def verify(current):
        # 确定性 Mock 检查桩：只演示编排协议，不冒充 C 的完整规则验证器。
        text = current["results"]["write"]["text"]
        refs = set(re.findall(r"\[([a-z]+:[A-Za-z0-9_-]+)\]", text))
        citation = 1.0 if refs and refs <= set(available_sources()) else 0.0
        consistent = current["results"]["analyze"]["consistent"]
        metrics = {"citation": citation, "consistency": 1.0 if consistent else 0.4,
                   "coverage": sum("## " + title in text for title in SECTIONS) / len(SECTIONS),
                   "logic": 1.0, "format": 1.0}
        issues = []
        for condition, target, message in [(not citation, "write", "缺少可解析引用"),
                                            (not consistent, "analyze", "Mock 数值冲突")]:
            if condition:
                issues.append({"section": "数据方案", "reason": message, "suggestion": "按证据修订该段",
                               "target_node": target, "severity": "blocker"})
        score = round(sum(policy["weights"][key] * value for key, value in metrics.items()), 3)
        card = {"run_id": run_id, "round": current["round"], "score": score,
                "threshold": policy["pass_threshold"], "metrics": metrics, "issues": issues,
                "verdict": "pass" if score >= policy["pass_threshold"] and not issues else "fail"}
        validator("scorecard.schema.json").validate(card)
        return card

    handlers = {
        "plan": lambda current: {"sections": SECTIONS},
        "retrieve": lambda current: retrieve(request) if scenario != "evidence_missing" else
            {"query": request, "mode": "hybrid", "items": []},
        "fanout": lambda current: {},
        "analyze": lambda current: {"consistent": scenario != "numeric_conflict" or current["round"] > 0},
        "outline": lambda current: {"sections": SECTIONS},
        "write": writer, "verify": verify,
        "gate": lambda current: asdict(controller.decide(current["results"]["verify"])),
        "revise": lambda current: current["results"]["gate"],
        "review": lambda current: {"accepted": current["results"]["verify"]["verdict"] == "pass"},
        "snap": lambda current: {"checkpoint_enabled": False},
    }

    def traced(node_id):
        def invoke(current):
            start = perf_counter()
            record(event(state["trace_id"], run_id, node_id, "start", round=current["round"],
                                input_value=current["results"]))
            try:
                result = handlers[node_id](current)
            except Exception as exc:
                record(event(state["trace_id"], run_id, node_id, "fail", round=current["round"],
                                    error_class=type(exc).__name__, reason="节点执行失败"))
                raise
            summary = ""
            if node_id == "verify":
                summary = f"Mock verdict={result['verdict']}, score={result['score']:.3f}"
            if node_id == "revise":
                summary = "定向回退：" + ",".join(result["targets"])
                record(event(state["trace_id"], run_id, node_id, "revise", round=current["round"], reason=summary))
            record(event(state["trace_id"], run_id, node_id, "end", round=current["round"],
                                output_value=result, duration_ms=int((perf_counter() - start) * 1000), reason=summary))
            return result
        return invoke

    wrapped = {node: traced(node) for node in graph.nodes}
    try:
        while True:
            if engine == "langgraph":
                state = compile_langgraph(graph, wrapped, active_nodes=active).invoke(state)
            else:
                for layer in graph.layers:
                    ready = [node for node in layer if node in active]
                    if "gate" in state["results"]:
                        action = state["results"]["gate"]["action"]
                        ready = [node for node in ready if (node != "revise" or action == "revise")
                                 and (node not in {"review", "snap"} or action == "pass")]
                    if not ready:
                        continue
                    with ThreadPoolExecutor(max_workers=len(ready)) as pool:
                        futures = {node: pool.submit(wrapped[node], state) for node in ready}
                        updates = {node: task.result() for node, task in futures.items()}
                    state["results"].update(updates)
            decision = state["results"]["gate"]
            reason = decision["reason"]
            if decision["action"] != "revise":
                if decision["action"] == "abort":
                    record(event(state["trace_id"], run_id, "gate", "abort", round=state["round"], reason=reason))
                break
            state["round"] = decision["round"]
            active = set(decision["rerun_nodes"]) | {"gate", "revise", "review", "snap"}
            state["results"] = {key: value for key, value in state["results"].items() if key not in active}
    except Exception as exc:
        reason = f"执行中止：{type(exc).__name__}"
        record(event(state["trace_id"], run_id, "gate", "abort", round=state["round"], reason=reason))
    card = state["results"].get("verify")
    if card is None:
        card = {"run_id": run_id, "round": state["round"], "score": 0, "threshold": policy["pass_threshold"],
                "metrics": {key: 0 for key in policy["weights"]}, "issues": [], "verdict": "abort"}
    result = {"run_id": run_id, "engine": engine, "scenario": scenario, "reason": reason,
              "scorecard": card, "events": events, "results": state["results"],
              "passed": state["results"].get("gate", {}).get("action") == "pass"}
    if output is not None:
        export(result, Path(output))
    return result


def export(result, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    solution = result["results"].get("write", {}).get("text", "# Mock 运行中止\n")
    evidence = sorted(set(re.findall(r"\[([a-z]+:[A-Za-z0-9_-]+)\]", solution)))
    for name, value in [("solution.md", solution), ("evidence_chain.json", evidence),
                        ("scorecard.json", result["scorecard"])]:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        (directory / name).write_text(text, encoding="utf-8")
    write_trace(directory / "trace.jsonl", result["events"])
    files = []
    for name in ["solution.md", "evidence_chain.json", "scorecard.json", "trace.jsonl"]:
        data = (directory / name).read_bytes()
        files.append({"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    # 交付包会被解压到**没有 .git** 的目录里（评审现场就是这样），
    # 所以不能直接读 git：优先环境变量，其次 git，最后用合法哨兵值。
    # delivery_artifact 要求 commit_sha 是 7-40 位十六进制，故哨兵取 "0000000"。
    commit = _commit_sha()
    artifact = {"solution": {"path": "solution.md", "sha256": files[0]["sha256"], "sections": list(SECTIONS)},
                "evidence_chain": evidence, "scorecard": result["scorecard"], "trace_bundle": result["events"],
                "manifest": {"genome_version": "d-mock-0.1", "commit_sha": commit,
                             "generated_at": result["events"][-1]["ts"], "mock": True, "files": files}}
    validator("delivery_artifact.schema.json").validate(artifact)
    (directory / "delivery_artifact.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", default="用机器视觉升级精密零件产线质检")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--engine", choices=["python", "langgraph"], default="python")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/d-demo")
    args = parser.parse_args()
    result = run_demo(args.request, scenario=args.scenario, engine=args.engine, output=args.output)
    print(f"[{'PASS' if result['passed'] else 'ABORT'}] {result['reason']}；round={result['scorecard']['round']}")
    print(f"交付物：{args.output.resolve()}")
    raise SystemExit(0 if result["passed"] else 1)
