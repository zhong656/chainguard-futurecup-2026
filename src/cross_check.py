"""L3：双路检索比对（Owner: B/C）。

它验什么
--------
L1 检查"引用是否存在"（`CITATION_UNKNOWN` 只能发现编造的 source_id）；
L2 用模型看逻辑。两者都**没有回答一个问题**：

    **这条引用，换一条检索路径还能找到吗？**

如果一条引用只有在"混合检索"（BM25 + 向量经 RRF 融合）里才排得靠前，
而单独用任一路径都检索不到它，那它很可能是**融合偏置**带来的弱支撑——
这不是"引用错误"，但属于"支撑不足"，值得标出来。

做法
----
对 Draft 里每个带引用的段落：

1. 用该段文本做 query；
2. 分别走 **BM25 单路** 与 **向量单路** 检索（各自 top_k）；
3. 若被引用的 `source_id` 在**任一路**命中 → 一致；
4. 两路都不命中 → `CROSS_CHECK_MISMATCH`。

聚合出 `agreement = 一致数 / 检查数`，作为 scorecard 的 `cross_check` 维度
（`scorecard.schema.json` 的 metrics 允许任意 0~1 数值，**不需要改契约**）。

严重度
------
`major`（不是 `blocker`）：L3 判断的是"支撑强度"，不是"引用真伪"。
真伪由 L1 管；L3 命中不会一票否决，但会进 issues 供人复核。
这条边界是有意的——把弱信号当硬结论，比不检查更糟。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src import knowledge_hub


@dataclass
class CrossCheckReport:
    checked: int = 0
    confirmed: int = 0
    issues: list[dict] = field(default_factory=list)

    @property
    def agreement(self) -> float:
        if self.checked == 0:
            return 1.0  # 没有引用可查时不算失败（L1 会报 CITATION_MISSING）
        return round(self.confirmed / self.checked, 4)

    def to_dict(self) -> dict:
        return {
            "checked": self.checked,
            "confirmed": self.confirmed,
            "agreement": self.agreement,
            "issues": self.issues,
        }


def _section_text(section: dict) -> str:
    """段落文本：契约里是 `content`（字符串），兼容早期 `paragraphs` 写法。"""
    parts = [str(section.get("title") or "")]
    content = section.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content)
    for para in section.get("paragraphs") or []:
        if isinstance(para, dict):
            parts.append(str(para.get("text") or ""))
        else:
            parts.append(str(para))
    return " ".join(p for p in parts if p).strip()


def _top_source_ids(query: str, chunks, mode: str, top_k: int) -> set[str]:
    result = knowledge_hub.retrieve(query, chunks=chunks, top_k=top_k, mode=mode)
    return {item["source_id"] for item in result.get("items", [])}


def cross_check(draft: dict, chunks=None, *, top_k: int = 8,
                modes: tuple[str, str] = ("bm25", "vector")) -> CrossCheckReport:
    """对 Draft 的每条引用做双路比对。

    `chunks` 不传时按默认索引构建（与主链路同一份索引，避免"两套语料"的假象）。
    """
    chunks = chunks if chunks is not None else knowledge_hub.build_index()
    report = CrossCheckReport()

    for section in draft.get("sections") or []:
        citations = [str(sid) for sid in (section.get("citations") or [])]
        if not citations:
            continue
        query = _section_text(section)
        if not query:
            continue

        for source_id in citations:
            report.checked += 1
            hits: list[str] = []
            for mode in modes:
                if source_id in _top_source_ids(query, chunks, mode, top_k):
                    hits.append(mode)
            if hits:
                report.confirmed += 1
                continue
            # 字段必须符合 contracts/scorecard.schema.json 的 issues.items：
            # required = section / reason / suggestion / target_node / severity，
            # severity 只有 blocker | warning —— 所以这里用 warning，不用自造的 major。
            report.issues.append({
                "rule_id": "CROSS_CHECK_MISMATCH",
                "severity": "warning",
                "target_node": "write",
                "section": section.get("title") or "",
                "reason": (
                    f"引用 {source_id} 在 {'/'.join(modes)} 任一路径的 top{top_k} 中均未出现；"
                    f"该引用可能只在融合排序下成立，支撑强度偏弱"
                ),
                "suggestion": "换用与该段更贴切的证据，或在段落中说明该来源的适用边界",
                "source_id": source_id,
            })

    return report


def to_scorecard_metric(report: CrossCheckReport) -> dict:
    """给 scorecard 用的 metric（契约允许 metrics 里出现新的 0~1 数值）。"""
    return {"cross_check": report.agreement}
