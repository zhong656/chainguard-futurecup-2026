"""A: four-provider routing and contract-safe remote responses without paid calls."""

from __future__ import annotations

import json

import pytest
import yaml

# httpx 是**可选依赖**（录屏/HTTP 服务才需要装）。没装时整模块 skip，
# 而不是让 pytest 在收集阶段报 ERROR——那会让 check.py 在干净环境里直接红。
# 与 tests/test_api.py 的写法保持一致。
httpx = pytest.importorskip("httpx", reason="llm 路由的 HTTP 传输测试需要 httpx")

from scripts._schema import validator
from src.llm_adapter import (
    LLMAdapterError, MockLLMAdapter, RemoteLLMAdapter, create_adapter, parse_draft,
)
from src import vertical_slice


RETRIEVAL = {
    "query": "质检", "mode": "hybrid", "items": [
        {"source_id": "kb:source1", "score": 1.0, "snippet": "稳定光源支持机器视觉质检。"},
    ],
}


def remote_reply(*, citation: str = "kb:source1") -> dict:
    draft = {
        "run_id": "test-run", "round": 0,
        "sections": [{"title": "现状痛点", "content": "稳定光源支持机器视觉质检。",
                      "citations": [citation]}],
    }
    return {
        "choices": [{"message": {"content": json.dumps(draft, ensure_ascii=False)},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }


@pytest.mark.parametrize("provider", ["deepseek", "qwen", "ollama"])
def test_remote_provider_normalizes_response(monkeypatch, provider):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    seen = []

    def respond(request):
        seen.append(request)
        return httpx.Response(200, json=remote_reply())

    adapter = create_adapter(transport=httpx.MockTransport(respond))
    response = adapter.generate_draft("质检", RETRIEVAL, run_id="test-run")
    validator("llm_response.schema.json").validate(response)
    assert response["provider"] == provider and response["mock"] is False
    assert response["usage"] == {"tokens_in": 12, "tokens_out": 8}
    assert parse_draft(response)["sections"][0]["citations"] == ["kb:source1"]
    assert seen[0].url.path.endswith("/chat/completions")
    assert json.loads(seen[0].content)["messages"][0]["content"].find("kb:source1") >= 0
    if provider == "ollama":
        assert "Authorization" not in seen[0].headers
    else:
        assert seen[0].headers["Authorization"] == "Bearer test-only-key"


def test_mock_does_not_read_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    adapter = create_adapter()
    assert isinstance(adapter, MockLLMAdapter)
    assert adapter.generate_draft("质检", RETRIEVAL, run_id="test-run")["usage"] == {
        "tokens_in": 0, "tokens_out": 0,
    }


def test_config_can_select_real_provider_and_keep_mock_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    from src.llm_adapter import CONFIG

    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["provider"] = "qwen"
    path = tmp_path / "llm.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    adapter = create_adapter(path, transport=httpx.MockTransport(lambda _: httpx.Response(429)))
    response = adapter.generate_draft("质检", RETRIEVAL, run_id="test-run")
    assert response["provider"] == "mock" and response["degraded"] is True


def test_remote_key_is_required_without_silent_mock(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(LLMAdapterError, match="LLM_API_KEY"):
        create_adapter(provider="deepseek")


def test_remote_cannot_invent_source_id(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=remote_reply(citation="kb:madeup")))
    adapter = create_adapter(provider="qwen", transport=transport)
    with pytest.raises(LLMAdapterError, match="source_id"):
        adapter.generate_draft("质检", RETRIEVAL, run_id="test-run")


def test_rate_limit_degrades_to_mock(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    transport = httpx.MockTransport(lambda _: httpx.Response(429))
    adapter = create_adapter(provider="deepseek", transport=transport)
    response = adapter.generate_draft("质检", RETRIEVAL, run_id="test-run")
    validator("llm_response.schema.json").validate(response)
    assert response["provider"] == "mock" and response["mock"] is True
    assert response["degraded"] is True


def test_unauthorized_does_not_degrade_to_mock(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    transport = httpx.MockTransport(lambda _: httpx.Response(401))
    adapter = create_adapter(provider="deepseek", transport=transport)
    with pytest.raises(LLMAdapterError, match="HTTP 401"):
        adapter.generate_draft("质检", RETRIEVAL, run_id="test-run")


def test_invalid_provider_payload_fails_without_echoing_content(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-only-key")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text="private response content"))
    adapter = create_adapter(provider="deepseek", transport=transport)
    with pytest.raises(LLMAdapterError, match="不是有效的 Draft JSON") as exc:
        adapter.generate_draft("质检", RETRIEVAL, run_id="test-run")
    assert "private response content" not in str(exc.value)


def test_manifest_uses_actual_provider(monkeypatch, tmp_path):
    mock = MockLLMAdapter()

    class FakeRemote:
        def generate_draft(self, *args, **kwargs):
            response = mock.generate_draft(*args, **kwargs)
            response.update(provider="deepseek", model="deepseek-chat", mock=False,
                            usage={"tokens_in": 12, "tokens_out": 8})
            return response

    monkeypatch.setattr(vertical_slice, "create_adapter", lambda: FakeRemote())
    result = vertical_slice.run_vertical_slice("机器视觉质检", output=tmp_path)
    assert result["llm_response"]["provider"] == "deepseek"
    assert result["artifact"]["manifest"]["mock"] is False
    assert "Mock" not in (tmp_path / "solution.md").read_text(encoding="utf-8").splitlines()[0]


def test_provider_fallback_is_visible_in_trace(monkeypatch, tmp_path):
    mock = MockLLMAdapter()

    class FakeFallback:
        def generate_draft(self, *args, **kwargs):
            response = mock.generate_draft(*args, **kwargs)
            response["degraded"] = True
            return response

    monkeypatch.setattr(vertical_slice, "create_adapter", lambda: FakeFallback())
    result = vertical_slice.run_vertical_slice("机器视觉质检", output=tmp_path)
    assert result["artifact"]["manifest"]["mock"] is True
    assert any(item["node_id"] == "write" and item["kind"] == "degrade" for item in result["events"])
