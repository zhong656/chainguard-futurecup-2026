"""检索评测 —— 给「知识库定义与集成」提供可复现的命中率证据（Owner: B）。

为什么要单独的评测集
------------------
`retrieve()` 能返回结果，不代表"查得准"。没有标注数据时，"命中率 90%" 只是形容词；
有了 `knowledge/eval/queries.yaml`（每条查询人工标注期望 source_id），
命中率就变成可复算的数字，换语料、改算法、调 top_k 都能对比。

指标口径
--------
- **hit@k**：期望的 source_id 出现在返回的前 k 条里，算命中
- **hit@1**：只有排第一也算命中，衡量"最相关的是不是最靠前"
- **MRR**  ：命中项排名的倒数（第 1 名 1.0、第 2 名 0.5…），无命中记 0
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

try:  # `python -m src.knowledge_eval` 与 `pytest`（src 在 sys.path 上）两种调用方式都要能跑
    from src import knowledge_hub as kh
except ImportError:  # pragma: no cover
    import knowledge_hub as kh

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERIES = ROOT / "knowledge" / "eval" / "queries.yaml"


class EvalError(ValueError):
    """评测集本身有问题（格式、空查询、期望 id 不存在等）。"""


@dataclass
class QueryResult:
    id: str
    query: str
    expected: list[str]
    got: list[str]
    rank: int | None  # 首个命中项的排名（1-based），未命中为 None

    @property
    def hit(self) -> bool:
        return self.rank is not None


@dataclass
class EvalReport:
    top_k: int
    results: list[QueryResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def hits(self) -> int:
        return sum(1 for r in self.results if r.hit)

    @property
    def hit_rate(self) -> float:
        return round(self.hits / self.total, 4) if self.total else 0.0

    @property
    def hit_at_1(self) -> float:
        first = sum(1 for r in self.results if r.rank == 1)
        return round(first / self.total, 4) if self.total else 0.0

    @property
    def mrr(self) -> float:
        if not self.total:
            return 0.0
        return round(sum(1.0 / r.rank for r in self.results if r.rank) / self.total, 4)

    @property
    def misses(self) -> list[QueryResult]:
        return [r for r in self.results if not r.hit]


def load_queries(path: Path = DEFAULT_QUERIES) -> dict:
    if not path.exists():
        raise EvalError(f"评测集不存在：{path}")
    import yaml  # 延迟导入

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    queries = data.get("queries") or []
    if not queries:
        raise EvalError("评测集为空")
    seen = set()
    for q in queries:
        qid = str(q.get("id", ""))
        if not qid or qid in seen:
            raise EvalError(f"id 缺失或重复：{qid!r}")
        seen.add(qid)
        if not str(q.get("query", "")).strip():
            raise EvalError(f"{qid}: query 为空")
        if not q.get("expected"):
            raise EvalError(f"{qid}: expected 不能为空（否则无法判定命中）")
    return data


def evaluate(
    chunks: list[kh.Chunk] | None = None,
    queries_path: Path = DEFAULT_QUERIES,
    top_k: int | None = None,
) -> EvalReport:
    """跑一遍评测集，返回可打印/可落盘的报告。"""
    data = load_queries(queries_path)
    k = int(top_k or data.get("top_k") or 8)
    chunks = chunks if chunks is not None else kh.build_index()
    if not chunks:
        raise EvalError("索引为空，无法评测")

    available = {c.source_id for c in chunks}
    report = EvalReport(top_k=k)
    for item in data["queries"]:
        expected = [str(s) for s in item["expected"]]
        unknown = [s for s in expected if s not in available]
        if unknown:
            raise EvalError(f"{item['id']}: 期望的 source_id 不存在于索引中：{unknown}")

        result = kh.retrieve(str(item["query"]), chunks=chunks, top_k=k)
        got = [i["source_id"] for i in result["items"]]
        rank = next((idx for idx, sid in enumerate(got, start=1) if sid in expected), None)
        report.results.append(
            QueryResult(id=str(item["id"]), query=str(item["query"]), expected=expected, got=got, rank=rank)
        )
    return report


def _groups(report: EvalReport) -> list[tuple[str, int, float, float, float]]:
    """按 id 前缀拆成「原文词」与「改述」两组 —— 只报总分容易高估。"""
    rows = []
    for name, keep in (("原文词（q*）", lambda r: not r.id.startswith("h")), ("改述（h*）", lambda r: r.id.startswith("h"))):
        subset = [r for r in report.results if keep(r)]
        if not subset:
            continue
        n = len(subset)
        hr = sum(1 for r in subset if r.hit) / n
        h1 = sum(1 for r in subset if r.rank == 1) / n
        mrr = round(sum(1.0 / r.rank for r in subset if r.rank) / n, 4)
        rows.append((name, n, hr, h1, mrr))
    return rows


def render_markdown(report: EvalReport) -> str:
    lines = [
        "# 检索命中率评测",
        "",
        "> 由 `src/knowledge_eval.py` 生成，**请勿手改**；改评测集或检索算法后重跑。",
        "",
        f"- 查询数：{report.total}",
        f"- 命中（hit@{report.top_k}）：{report.hits} / {report.total} = **{report.hit_rate:.2%}**",
        f"- 命中@1：{report.hit_at_1:.2%}",
        f"- MRR：{report.mrr}",
        "",
        "## 分组（id 以 h 开头的是改述查询，不直接复用原文用词）",
        "",
        "| 组 | 查询数 | hit@k | hit@1 | MRR |",
        "| --- | --- | --- | --- | --- |",
        *[f"| {name} | {n} | {hr:.2%} | {h1:.2%} | {mrr} |" for name, n, hr, h1, mrr in _groups(report)],
        "",
        "| id | 查询 | 期望 | 首个命中排名 | 结果 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report.results:
        rank = f"{r.rank}" if r.rank else "—"
        mark = "命中" if r.hit else "**未命中**"
        lines.append(f"| {r.id} | {r.query} | {', '.join(r.expected)} | {rank} | {mark} |")
    if report.misses:
        lines += ["", "## 未命中明细", ""]
        for r in report.misses:
            lines.append(f"- {r.id} `{r.query}`：期望 {r.expected}，实际返回 {r.got[:3]}")
    return "\n".join(lines) + "\n"


def main() -> int:
    report = evaluate()
    out = ROOT / "outputs" / "retrieval-eval.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(report), encoding="utf-8")
    print(
        f"hit@{report.top_k}={report.hit_rate:.2%}  hit@1={report.hit_at_1:.2%}  "
        f"MRR={report.mrr}  查询数={report.total}"
    )
    print(f"报告：{out.relative_to(ROOT)}")
    return 0 if report.hit_rate >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
