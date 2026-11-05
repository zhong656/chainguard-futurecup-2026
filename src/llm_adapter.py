"""统一 LLM 响应的离线 Mock 档；真实 provider 在后续阶段接入。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts._schema import validator

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "llm.yaml"
SECTIONS = ("现状痛点", "技术选型", "数据方案", "实施阶段", "成本与ROI", "风险与合规")
PREFERRED_SOURCE = (
    "mv:doc001", "web:doc007", "mv:doc001", "mv:doc002", "csv:param001", "mv:doc003"
)


class LLMAdapterError(RuntimeError):
    """模型配置或调用无法产生成功响应。"""


class MockLLMAdapter:
    """从已检索的片段生成可验证草稿，绝不自造 source_id。"""

    def __init__(self, config_path: Path = CONFIG) -> None:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("provider") != "mock":
            raise LLMAdapterError("当前纵切只支持 configs/llm.yaml 的 mock provider")
        model = (config.get("providers") or {}).get("mock", {}).get("strong")
        if not isinstance(model, str) or not model:
            raise LLMAdapterError("Mock strong 模型名未配置")
        self.model = model

    def generate_draft(
        self, request: str, retrieval: dict, *, run_id: str, round: int = 0,
        omit_first_citation: bool = False,
    ) -> dict:
        """返回 llm_response；content 是 Draft JSON，调用方负责解析和验契约。"""
        if not isinstance(request, str) or not request.strip():
            raise ValueError("需求不能为空")
        validator("retrieval_result.schema.json").validate(retrieval)
        items = retrieval["items"]
        if not items:
            raise LLMAdapterError("检索结果为空，不能生成有据可查的草稿")
        by_id = {item["source_id"]: item for item in items}
        sections = []
        for index, title in enumerate(SECTIONS):
            item = by_id.get(PREFERRED_SOURCE[index], items[index % len(items)])
            source_id = item["source_id"]
            snippet = str(item.get("snippet") or "").strip()
            if not snippet:
                raise LLMAdapterError(f"检索片段为空：{source_id}")
            sections.append({
                "title": title,
                "content": f"离线示例资料摘录（正式方案须复核来源）：{snippet}",
                "citations": [] if omit_first_citation and index == 0 else [source_id],
            })
        draft = {"run_id": run_id, "round": round, "sections": sections}
        validator("draft.schema.json").validate(draft)
        response = {
            "provider": "mock", "model": self.model, "tier": "strong",
            "content": json.dumps(draft, ensure_ascii=False),
            "usage": {"tokens_in": 0, "tokens_out": 0},
            "latency_ms": 0, "finish_reason": "stop", "degraded": False, "mock": True,
        }
        validator("llm_response.schema.json").validate(response)
        return response


def parse_draft(response: dict) -> dict:
    validator("llm_response.schema.json").validate(response)
    try:
        draft = json.loads(response["content"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise LLMAdapterError("模型响应不是 Draft JSON") from exc
    validator("draft.schema.json").validate(draft)
    return draft
