"""EvidencePool —— 证据链组装与回溯（Owner: B）。

职责边界（对应 contracts/）：
    - `retrieval_result` 是检索的**返回**，含多条带分数的命中
    - `evidence_chain` 是交付包里的**引用清单**，只有 source_id 字符串，去重且有序
    - `source_ref` 是单个证据的**完整结构**，含文件、位置、原文片段、哈希

本模块只做转换与回溯，不做检索、不做评分。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

try:
    from . import knowledge_hub as kh
except ImportError:  # 兼容直接把 src/ 加入 sys.path 的现有调用方
    import knowledge_hub as kh

ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT = 2000  # 与 docs/api.md 的口径一致：只存被引用片段，不存全文


class EvidenceError(ValueError):
    """证据链相关错误：未知 source_id、结构不合法等。"""


def _doc_id(source_id: str) -> str:
    """从 source_id 推导 doc_id：`mv:doc001` → `doc001`。

    sources.yaml 没有 doc_id 字段，而 source_ref 要求必填，
    统一按冒号后的部分取，保证可重复推导、不引入第二处定义。
    """
    _, _, tail = source_id.partition(":")
    return tail or source_id


class EvidencePool:
    """一次运行内的证据池：按加入顺序去重，可导出 chain 与完整 ref。"""

    def __init__(self, chunks: list[kh.Chunk] | None = None) -> None:
        self._chunks = chunks if chunks is not None else kh.build_index()
        self._by_source: dict[str, list[kh.Chunk]] = {}
        for c in self._chunks:
            self._by_source.setdefault(c.source_id, []).append(c)
        self._order: list[str] = []

    # ---------------- 组装 ---------------- #

    def add_from_retrieval(self, result: dict) -> list[str]:
        """把一个 retrieval_result 的命中并入证据池，返回本次新增的 source_id。"""
        added: list[str] = []
        for item in result.get("items") or []:
            sid = str(item.get("source_id", ""))
            if not sid:
                continue
            if sid not in self._by_source:
                raise EvidenceError(f"证据池中不存在的 source_id：{sid}（检索结果必须来自本库）")
            if sid not in self._order:
                self._order.append(sid)
                added.append(sid)
        return added

    def to_chain(self) -> list[str]:
        """交付包里的 evidence_chain：去重、保持首次命中顺序。"""
        return list(self._order)

    # ---------------- 回溯 ---------------- #

    def refs_for(self, source_id: str) -> list[dict]:
        """某个 source_id 的全部片段引用（一段一个 source_ref）。"""
        chunks = self._by_source.get(source_id)
        if not chunks:
            raise EvidenceError(f"未知 source_id：{source_id}")
        return [self._to_ref(c) for c in chunks]

    def resolve(self, source_id: str) -> dict:
        """解析成一条代表性 source_ref（取首个片段）。

        需要逐段引用时用 `refs_for()`。
        """
        return self.refs_for(source_id)[0]

    def resolve_chain(self, chain: list[str] | None = None) -> list[dict]:
        """把 evidence_chain 整体解析成 source_ref 列表，缺一个就报错。"""
        chain = chain if chain is not None else self.to_chain()
        missing = [sid for sid in chain if sid not in self._by_source]
        if missing:
            raise EvidenceError(f"证据链中有无法回溯的 source_id：{missing}")
        return [self.resolve(sid) for sid in chain]

    # ---------------- 内部 ---------------- #

    def _to_ref(self, chunk: kh.Chunk) -> dict:
        text = chunk.text if len(chunk.text) <= MAX_TEXT else chunk.text[:MAX_TEXT]
        return {
            "source_id": chunk.source_id,
            "doc_id": _doc_id(chunk.source_id),
            "file_path": chunk.path,
            "page": None,
            "row": None,
            "char_range": [chunk.start, chunk.end],
            "text": text,
            "hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            "version": "v1",
        }


def build_chain(results: list[dict], chunks: list[kh.Chunk] | None = None) -> list[str]:
    """便捷函数：从多个 retrieval_result 直接得到 evidence_chain。"""
    pool = EvidencePool(chunks)
    for r in results:
        pool.add_from_retrieval(r)
    return pool.to_chain()
