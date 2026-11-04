"""KnowledgeHub —— 检索与证据链（Owner: B）。

当前阶段（11/05–11/07）只做 **Mock 可跑版**：
    - 语料来自 knowledge/corpus/ 的本地文件
    - 双路召回：词频/IDF（模拟 BM25） + 字符二元组余弦（模拟向量）
    - 融合：RRF，k=60（口径见 docs/api.md 与 contracts/retrieval_result.schema.json）
    - 输出严格符合 retrieval_result 契约

不依赖 Chroma、不依赖任何 embedding 模型、不联网。
阶段 2 再把「向量路」替换成 Chroma，接口不变。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "knowledge" / "sources.yaml"
DEFAULT_CORPUS = ROOT / "knowledge" / "corpus"
DEFAULT_INDEX = ROOT / "knowledge" / "source_index.json"

RRF_K = 60
SNIPPET_LEN = 120

_CJK = r"\u4e00-\u9fff"
_TOKEN_RE = re.compile(rf"[a-z0-9]+|[{_CJK}]")


@dataclass(frozen=True)
class Chunk:
    """一个可检索的最小单元。`source_id` 与 sources.yaml 一致，位置用 char_range 表达。"""

    source_id: str
    doc_id: str
    path: str
    start: int
    end: int
    text: str
    hash: str


# --------------------------------------------------------------------------- #
# 建索引
# --------------------------------------------------------------------------- #


def load_sources(path: Path = DEFAULT_SOURCES) -> list[dict]:
    """读取语料声明。缺文件时返回空列表（Mock 阶段允许没有语料）。"""
    if not path.exists():
        return []
    import yaml  # 延迟导入：只有需要读 YAML 时才依赖它

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("sources") or [])


def _split_paragraphs(text: str) -> list[tuple[int, int]]:
    """按空行切段，返回每段的 (start, end) 字符区间。

    跳过 Markdown 标题块：标题不含论证内容，若参与检索会霸占 snippet，
    让结果看起来"只命中了标题"。
    """
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\s*\n)[^\n]+)*", text):
        start, end = match.span()
        piece = text[start:end].strip()
        if not piece or piece.startswith("#"):
            continue
        spans.append((start, end))
    return spans


def build_index(
    sources: list[dict] | None = None,
    corpus_dir: Path = DEFAULT_CORPUS,
) -> list[Chunk]:
    """把语料声明 + 文件内容展开成 Chunk 列表（一段一块）。"""
    sources = sources if sources is not None else load_sources()
    chunks: list[Chunk] = []
    for src in sources:
        rel = str(src.get("path", ""))
        source_id = str(src.get("source_id", ""))
        if not rel or not source_id:
            continue
        f = corpus_dir.parent / rel if not Path(rel).is_absolute() else Path(rel)
        # sources.yaml 里的 path 形如 corpus/xxx.md，相对点是 knowledge/
        if not f.exists():
            f = ROOT / "knowledge" / rel
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        for start, end in _split_paragraphs(text):
            piece = text[start:end]
            chunks.append(
                Chunk(
                    source_id=source_id,
                    doc_id=str(src.get("doc_id") or ""),
                    path=rel,
                    start=start,
                    end=end,
                    text=piece,
                    hash=hashlib.sha256(piece.encode("utf-8")).hexdigest()[:16],
                )
            )
    return chunks


def save_index(chunks: list[Chunk], path: Path = DEFAULT_INDEX) -> Path:
    """写出 source_index.json —— 供 `evidence_chain` 解析检查使用。

    注意：该文件是**产物**，其内容是 source_id 的可解析清单；
    是否入库由团队决定（当前入库，因为它稳定且体积小）。
    """
    by_id: dict[str, dict] = {}
    for c in chunks:
        entry = by_id.setdefault(
            c.source_id, {"source_id": c.source_id, "path": c.path, "chunks": 0, "chars": 0}
        )
        entry["chunks"] += 1
        entry["chars"] += len(c.text)
    payload = {
        "version": 1,
        "generated_by": "scripts/gen_source_index.py",
        "count": len(by_id),
        "sources": sorted(by_id.values(), key=lambda x: x["source_id"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 检索
# --------------------------------------------------------------------------- #


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _bigrams(text: str) -> Counter:
    clean = re.sub(r"\s+", "", text.lower())
    return Counter(clean[i : i + 2] for i in range(max(0, len(clean) - 1)))


def _idf(index: list[Chunk]) -> dict[str, float]:
    n = len(index)
    df: Counter = Counter()
    for c in index:
        df.update(set(_tokens(c.text)))
    return {t: math.log((n + 1) / (df[t] + 1)) + 1.0 for t in df}


def _lexical_scores(index: list[Chunk], query: str, idf: dict[str, float]) -> list[float]:
    q_tokens = set(_tokens(query))
    scores: list[float] = []
    for c in index:
        tf = Counter(_tokens(c.text))
        total = sum(tf[t] * idf.get(t, 1.0) for t in q_tokens)
        scores.append(total / (1.0 + math.log(1 + len(c.text))) if total else 0.0)
    return scores


def _vector_scores(index: list[Chunk], query: str) -> list[float]:
    q = _bigrams(query)
    if not q:
        return [0.0] * len(index)
    q_norm = math.sqrt(sum(v * v for v in q.values())) or 1.0
    scores: list[float] = []
    for c in index:
        d = _bigrams(c.text)
        d_norm = math.sqrt(sum(v * v for v in d.values())) or 1.0
        dot = sum(q[g] * d.get(g, 0) for g in q)
        scores.append(dot / (q_norm * d_norm) if dot else 0.0)
    return scores


def _rrf(rankings: list[list[int]], k: int = RRF_K) -> list[float]:
    """Reciprocal Rank Fusion：多路名次融合，避免不同量纲的分数直接相加。"""
    fused = [0.0] * len(rankings[0]) if rankings else []
    for ranking in rankings:
        for position, idx in enumerate(ranking, start=1):
            fused[idx] += 1.0 / (k + position)
    return fused


def _ranking(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)


def retrieve(
    query: str,
    chunks: list[Chunk] | None = None,
    top_k: int = 8,
    mode: str = "hybrid",
) -> dict:
    """检索并返回符合 `retrieval_result` 契约的字典。

    mode: vector | bm25 | hybrid（hybrid 走 RRF k=60）
    """
    if not query or not query.strip():
        raise ValueError("query 不能为空")
    if mode not in {"vector", "bm25", "hybrid"}:
        raise ValueError(f"不支持的 mode: {mode}")

    chunks = chunks if chunks is not None else build_index()
    if not chunks:
        return {"query": query, "mode": mode, "top_k": top_k, "items": []}

    idf = _idf(chunks)
    lex = _lexical_scores(chunks, query, idf)
    vec = _vector_scores(chunks, query)

    if mode == "bm25":
        fused = lex
    elif mode == "vector":
        fused = vec
    else:
        fused = _rrf([_ranking(lex), _ranking(vec)])

    # 同一文档多段命中时只保留最高分那段，避免同一 source_id 霸屏
    best: dict[str, tuple[float, int]] = {}
    for i, score in enumerate(fused):
        if score <= 0:
            continue
        sid = chunks[i].source_id
        if sid not in best or score > best[sid][0]:
            best[sid] = (score, i)

    ordered = sorted(best.values(), key=lambda x: x[0], reverse=True)[:top_k]
    peak = ordered[0][0] if ordered else 1.0
    items = []
    for rank, (score, i) in enumerate(ordered, start=1):
        text = re.sub(r"\s+", " ", chunks[i].text).strip()
        items.append(
            {
                "source_id": chunks[i].source_id,
                "score": round(min(1.0, score / peak), 6),  # 归一化到 0..1
                "rank": rank,
                "snippet": text[:SNIPPET_LEN],
            }
        )
    return {"query": query, "mode": mode, "top_k": top_k, "items": items}


def available_sources(chunks: list[Chunk] | None = None) -> list[str]:
    """返回可解析的 source_id 列表（供 evidence_chain 校验用）。"""
    chunks = chunks if chunks is not None else build_index()
    return sorted({c.source_id for c in chunks})


if __name__ == "__main__":
    import sys as _sys

    _chunks = build_index()
    _path = save_index(_chunks)
    print(f"索引完成：{len(_chunks)} 个片段 → {_path.relative_to(ROOT)}")
    _sys.exit(0 if _chunks else 1)