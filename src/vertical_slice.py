"""离线纵切：需求 → 检索 → Mock 草稿 → L1 评分 → 定向修订 → 导出。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import yaml

from scripts._schema import validator
from src.dag_compiler import compile_workflow
from src.evidence import EvidencePool
from src.knowledge_hub import DEFAULT_CORPUS, DEFAULT_SOURCES, build_index, load_sources, retrieve
from src.llm_adapter import MockLLMAdapter, parse_draft
from src.loop_controller import LoopController
from src.rule_checker import check
from src.verifier import default_verifier
from src.trace import digest, event, write_trace

ROOT = Path(__file__).resolve().parents[1]


class VerticalSliceError(RuntimeError):
    """纵切未形成可交付结果。"""


def _render_solution(draft: dict) -> str:
    lines = ["# 产业技术方案（Mock 离线演示，非正式交付）", ""]
    for section in draft["sections"]:
        lines.extend((f"## {section['title']}", "", section["content"], ""))
        lines.extend(f"[{source_id}]" for source_id in section["citations"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _commit_sha() -> str:
    """容器/zip 里没有 .git，优先读环境变量，其次 git，最后 unknown。"""
    import os
    if os.environ.get("GIT_COMMIT"):
        return os.environ["GIT_COMMIT"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _render_charts(result: dict, directory: Path) -> list[Path]:
    """评分卡五维 + Self-Loop 收敛曲线。图表也进 manifest，否则"可核验"只覆盖文本。"""
    from src.tools import chart

    charts = directory / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    metrics = result["scorecard"]["metrics"]
    out = [chart.bar_chart(list(metrics), [float(v) for v in metrics.values()],
                         charts / "scorecard.svg", title="评分卡五维")]
    rounds = result.get("rounds") or []
    if rounds:
        out.append(chart.line_chart(
            [f"R{r['round']}" for r in rounds],
            [float(r["score"]) for r in rounds],
            charts / "convergence.svg",
            title="Self-Loop 收敛",
            threshold=float(result["scorecard"]["threshold"]),
        ))
    return out


def export_delivery(result: dict, directory: Path) -> dict:
    """校验真实引用，写四件交付物及可复核的 manifest。"""
    if result["scorecard"]["verdict"] != "pass":
        raise VerticalSliceError("评分未通过，不能导出成功交付包")
    draft = result["draft"]
    retrieval_ids = {item["source_id"] for item in result["retrieval"]["items"]}
    cited = list(dict.fromkeys(sid for section in draft["sections"] for sid in section["citations"]))
    if not cited or not set(cited) <= retrieval_ids:
        raise VerticalSliceError("草稿引用缺失或引用了本次检索之外的 source_id")
    pool = EvidencePool(result["chunks"])
    pool.add_from_retrieval({"items": [{"source_id": sid} for sid in cited]})
    evidence_chain = pool.to_chain()
    for source_ref in pool.resolve_chain():
        validator("source_ref.schema.json").validate(source_ref)

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "solution.md").write_text(_render_solution(draft), encoding="utf-8")
    (directory / "evidence_chain.json").write_text(
        json.dumps(evidence_chain, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "scorecard.json").write_text(
        json.dumps(result["scorecard"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_trace(directory / "trace.jsonl", result["events"])
    (directory / "rounds.json").write_text(
        json.dumps(result.get("rounds", []), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    chart_paths = _render_charts(result, directory)
    names = ("solution.md", "evidence_chain.json", "scorecard.json", "trace.jsonl", "rounds.json")
    files = []
    for name in names:
        payload = (directory / name).read_bytes()
        files.append({"path": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
    for path in chart_paths:
        payload = path.read_bytes()
        files.append({"path": f"charts/{path.name}", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
    commit_sha = _commit_sha()
    artifact = {
        "solution": {"path": "solution.md", "sha256": files[0]["sha256"],
                     "sections": [section["title"] for section in draft["sections"]]},
        "evidence_chain": evidence_chain,
        "scorecard": result["scorecard"],
        "trace_bundle": result["events"],
        "manifest": {"genome_version": result["config_version"], "commit_sha": commit_sha,
                     "generated_at": datetime.now(timezone.utc).isoformat(), "mock": True,
                     "files": files},
    }
    validator("delivery_artifact.schema.json").validate(artifact)
    (directory / "delivery_artifact.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def run_vertical_slice(
    request: str, *, output: Path | None = None, sources_path: Path = DEFAULT_SOURCES,
    corpus_dir: Path = DEFAULT_CORPUS, inject_initial_gap: bool = True,
    run_id: str | None = None,
) -> dict:
    """按已编译 DAG 执行 Mock 纵切；首轮可注入一次缺引用以验证回退。"""
    if not isinstance(request, str) or not request.strip():
        raise ValueError("需求不能为空")
    if not sources_path.exists():
        raise VerticalSliceError(f"语料清单不存在：{sources_path}")
    sources = load_sources(sources_path)
    chunks = build_index(sources, corpus_dir)
    missing = {source["source_id"] for source in sources} - {chunk.source_id for chunk in chunks}
    if missing:
        raise VerticalSliceError(f"语料条目缺少可读取片段：{sorted(missing)}")
    if not chunks:
        raise VerticalSliceError("语料清单没有可检索片段")
    graph = compile_workflow(ROOT / "workflows" / "industry_solution.yaml")
    policy = yaml.safe_load((ROOT / "configs" / "verifier.yaml").read_text(encoding="utf-8"))["scorecard"]
    adapter = MockLLMAdapter()
    controller = LoopController(graph, policy)
    run_id = run_id or "mock-" + uuid4().hex[:12]
    trace_id = run_id + "-trace"
    config_version = digest({"workflow": graph.nodes, "loop": graph.loop, "policy": policy})
    results: dict = {}
    events: list[dict] = []
    rounds: list[dict] = []   # 每轮评分卡：fail→pass 的物证，最终写进 rounds.json
    active = set(graph.nodes)
    round_number = 0
    pool = EvidencePool(chunks)

    def execute(node_id: str):
        if node_id == "plan":
            return {"request_digest": digest(request)}
        if node_id == "retrieve":
            retrieval = retrieve(request, chunks=chunks)
            validator("retrieval_result.schema.json").validate(retrieval)
            if not retrieval["items"]:
                raise VerticalSliceError("检索没有可用证据")
            pool.add_from_retrieval(retrieval)
            return retrieval
        if node_id == "fanout":
            return {"retrieval_ready": True}
        if node_id == "analyze":
            return {"source_count": len(results["retrieve"]["items"])}
        if node_id == "outline":
            return {"sections": 6}
        if node_id == "write":
            response = adapter.generate_draft(
                request, results["retrieve"], run_id=run_id, round=round_number,
                omit_first_citation=inject_initial_gap and round_number == 0,
            )
            return {"response": response, "draft": parse_draft(response)}
        if node_id == "verify":
            # L2 内部会先跑 L1 再合并，这里不要重复调用 check
            return default_verifier().verify(results["write"]["draft"], pool)
        if node_id == "gate":
            return asdict(controller.decide(results["verify"]))
        if node_id == "revise":
            return results["gate"]
        if node_id == "review":
            return {"accepted": results["verify"]["verdict"] == "pass"}
        if node_id == "snap":
            return {"checkpoint_enabled": False}
        raise VerticalSliceError(f"未实现工作流节点：{node_id}")

    while True:
        for layer in graph.layers:
            for node_id in layer:
                if node_id not in active:
                    continue
                if "gate" in results:
                    action = results["gate"]["action"]
                    if node_id == "revise" and action != "revise":
                        continue
                    if node_id in {"review", "snap"} and action != "pass":
                        continue
                started = perf_counter()
                events.append(event(trace_id, run_id, node_id, "start", round=round_number,
                                    input_value={"node": node_id, "round": round_number},
                                    config_version=config_version))
                try:
                    value = execute(node_id)
                except Exception as exc:
                    events.append(event(trace_id, run_id, node_id, "fail", round=round_number,
                                        error_class=type(exc).__name__, reason="节点执行失败",
                                        config_version=config_version))
                    raise
                results[node_id] = value
                events.append(event(trace_id, run_id, node_id, "end", round=round_number,
                                    output_value=value, duration_ms=int((perf_counter() - started) * 1000),
                                    config_version=config_version))
        card = results["verify"]
        rounds.append({
            "round": round_number,
            "score": card["score"],
            "verdict": card["verdict"],
            "issues": card["issues"],
        })
        decision = results["gate"]
        if decision["action"] == "pass":
            break
        if decision["action"] != "revise":
            raise VerticalSliceError(f"定向修订中止：{decision['reason']}")
        events.append(event(trace_id, run_id, "revise", "revise", round=round_number,
                            reason="定向回退：" + ",".join(decision["targets"]),
                            config_version=config_version))
        round_number = decision["round"]
        # LoopController 只返回到 verify 为止的重算路径；gate 与出口须重跑。
        active = set(decision["rerun_nodes"]) | {"gate", "revise", "review", "snap"}
        results = {node: value for node, value in results.items() if node not in active}

    result = {
        "run_id": run_id, "round": round_number, "draft": results["write"]["draft"],
        "llm_response": results["write"]["response"], "retrieval": results["retrieve"],
        "scorecard": results["verify"], "events": events, "chunks": chunks, "rounds": rounds,
        "config_version": config_version,
    }
    if output is not None:
        result["artifact"] = export_delivery(result, Path(output))
    return result
