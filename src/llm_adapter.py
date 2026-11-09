"""四档 LLM 适配；默认 Mock，真实调用使用 OpenAI 兼容接口。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import yaml
from jsonschema import ValidationError

from scripts._schema import validator

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "llm.yaml"
SECTIONS = ("现状痛点", "技术选型", "数据方案", "实施阶段", "成本与ROI", "风险与合规")
PREFERRED_SOURCE = (
    "mv:doc001", "web:doc007", "mv:doc001", "mv:doc002", "csv:param001", "mv:doc003"
)


class LLMAdapterError(RuntimeError):
    """模型配置或调用无法产生成功响应。"""


class LLMTransientError(LLMAdapterError):
    """超时、限流或服务端错误，可按配置降级到 Mock。"""


class MockLLMAdapter:
    """从已检索的片段生成可验证草稿，绝不自造 source_id。"""

    def __init__(self, config_path: Path = CONFIG) -> None:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise LLMAdapterError("LLM 配置必须是 YAML 对象")
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


DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "ollama": "http://127.0.0.1:11434/v1",
}


class RemoteLLMAdapter:
    """把三个 OpenAI 兼容端点收敛为冻结的 LLMResponse 契约。"""

    def __init__(self, provider: str, config: dict, *, transport=None) -> None:
        if provider not in DEFAULT_BASE_URLS:
            raise LLMAdapterError(f"不支持的 provider：{provider}")
        self.provider = provider
        self.config = config
        self.transport = transport
        self.model = (config.get("providers") or {}).get(provider, {}).get("strong")
        if not isinstance(self.model, str) or not self.model.strip():
            raise LLMAdapterError(f"{provider} 的 strong 模型名未配置")
        self.api_key = "" if provider == "ollama" else os.environ.get("LLM_API_KEY", "")
        if provider != "ollama" and not self.api_key:
            raise LLMAdapterError(f"{provider} 需要环境变量 LLM_API_KEY")
        self.base_url = os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URLS[provider]
        if not self.base_url.startswith(("https://", "http://")):
            raise LLMAdapterError("LLM_BASE_URL 必须是 http(s) 地址")

    def generate_draft(
        self, request: str, retrieval: dict, *, run_id: str, round: int = 0,
        omit_first_citation: bool = False,
    ) -> dict:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("需求不能为空")
        validator("retrieval_result.schema.json").validate(retrieval)
        items = retrieval["items"]
        if not items:
            raise LLMAdapterError("检索结果为空，不能生成有据可查的草稿")
        tier = (self.config.get("routing") or {}).get("writer", "strong")
        settings = (self.config.get("tiers") or {}).get(tier)
        model = (self.config.get("providers") or {}).get(self.provider, {}).get(tier)
        if not isinstance(settings, dict) or not isinstance(model, str) or not model.strip():
            raise LLMAdapterError(f"{self.provider}/{tier} 模型配置不完整")
        import httpx

        allowed = {item["source_id"] for item in items}
        prompt = (
            "按需求生成六章中文产业技术方案草稿。只输出 Draft JSON，字段为 run_id、round、sections；"
            "每章字段为 title、content、citations。引用只能从下列 source_id 中选，不得自造。\n"
            + json.dumps({"request": request, "run_id": run_id, "round": round,
                          "sections": SECTIONS, "evidence": items}, ensure_ascii=False)
        )
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": settings["temperature"],
            "max_tokens": settings["max_tokens"],
            "response_format": {"type": "json_object"},
        }
        started = time.perf_counter()
        try:
            with httpx.Client(transport=self.transport, timeout=settings["timeout_s"]) as client:
                reply = client.post(self.base_url.rstrip("/") + "/chat/completions", json=payload,
                                    headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LLMTransientError(f"{self.provider} 连接失败或超时") from exc
        if reply.status_code == 429 or reply.status_code >= 500:
            raise LLMTransientError(f"{self.provider} 返回 HTTP {reply.status_code}")
        if reply.status_code >= 400:
            raise LLMAdapterError(f"{self.provider} 返回 HTTP {reply.status_code}")
        try:
            data = reply.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data["usage"]
            draft = json.loads(content)
            validator("draft.schema.json").validate(draft)
            if draft["run_id"] != run_id or draft.get("round", 0) != round:
                raise LLMAdapterError("模型草稿的 run_id 或 round 与本次调用不一致")
            if any(set(section.get("citations", [])) - allowed for section in draft["sections"]):
                raise LLMAdapterError("模型草稿引用了本次检索之外的 source_id")
            response = {
                "provider": self.provider, "model": model, "tier": tier,
                "content": json.dumps(draft, ensure_ascii=False),
                "usage": {"tokens_in": usage["prompt_tokens"],
                          "tokens_out": usage["completion_tokens"]},
                "latency_ms": max(0, int((time.perf_counter() - started) * 1000)),
                "finish_reason": str(choice.get("finish_reason") or "unknown"),
                "degraded": False, "mock": False,
            }
            validator("llm_response.schema.json").validate(response)
            return response
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            raise LLMAdapterError(f"{self.provider} 响应不是有效的 Draft JSON") from exc


class FallbackLLMAdapter:
    """只在可重试的供应商故障时，按配置降级到离线 Mock。"""

    def __init__(self, primary: RemoteLLMAdapter, fallback: MockLLMAdapter) -> None:
        self.primary = primary
        self.fallback = fallback

    def generate_draft(self, *args, **kwargs) -> dict:
        try:
            return self.primary.generate_draft(*args, **kwargs)
        except LLMTransientError:
            response = self.fallback.generate_draft(*args, **kwargs)
            response["degraded"] = True
            validator("llm_response.schema.json").validate(response)
            return response


def create_adapter(config_path: Path = CONFIG, *, provider: str | None = None, transport=None):
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise LLMAdapterError("LLM 配置必须是 YAML 对象")
    selected = provider or os.environ.get("LLM_PROVIDER") or config.get("provider", "mock")
    if selected == "mock":
        return MockLLMAdapter(config_path)
    primary = RemoteLLMAdapter(selected, config, transport=transport)
    fallback_chain = (config.get("fallback") or {}).get((config.get("routing") or {}).get("writer", "strong"), [])
    if "mock" in fallback_chain:
        return FallbackLLMAdapter(primary, MockLLMAdapter(config_path))
    return primary


def parse_draft(response: dict) -> dict:
    validator("llm_response.schema.json").validate(response)
    try:
        draft = json.loads(response["content"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise LLMAdapterError("模型响应不是 Draft JSON") from exc
    validator("draft.schema.json").validate(draft)
    return draft
