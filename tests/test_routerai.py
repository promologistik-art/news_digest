"""Tests for RouterAI client response parsing and HTTP behavior."""

from __future__ import annotations

import httpx
import pytest

from news_digest.ai.routerai import RouterAIClient, RouterAIError
from news_digest.config import Settings


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, routerai_api_key="test-secret", **overrides)


@pytest.mark.asyncio
async def test_chat_parses_response_and_usage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://routerai.ru/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(
            200,
            headers={"x-request-id": "header-id"},
            json={
                "id": "chatcmpl-123",
                "model": "deepseek/deepseek-v4.1-flash",
                "provider": "DeepSeek",
                "choices": [{"message": {"role": "assistant", "content": "готово"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RouterAIClient(settings(), http_client=http)
        result = await client.chat(messages=[{"role": "user", "content": "ping"}])

    assert result.content == "готово"
    assert result.model == "deepseek/deepseek-v4.1-flash"
    assert result.provider == "DeepSeek"
    assert result.request_id == "chatcmpl-123"
    assert result.usage is not None
    assert result.usage.total_tokens == 15


@pytest.mark.asyncio
async def test_missing_key_fails_before_network() -> None:
    client = RouterAIClient(Settings(_env_file=None))
    with pytest.raises(RouterAIError, match="ROUTERAI_API_KEY"):
        await client.chat(messages=[{"role": "user", "content": "ping"}])


@pytest.mark.asyncio
async def test_http_401_is_reported_without_response_body() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="secret-looking provider diagnostics")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RouterAIClient(settings(), http_client=http)
        with pytest.raises(RouterAIError, match="HTTP 401") as error:
            await client.chat(messages=[{"role": "user", "content": "ping"}])

    assert "secret-looking" not in str(error.value)


@pytest.mark.asyncio
async def test_retries_server_error_then_succeeds() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}], "model": "test-model"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = RouterAIClient(settings(ai_max_retries=1), http_client=http)
        result = await client.chat(messages=[{"role": "user", "content": "ping"}])

    assert calls == 2
    assert result.content == "ok"
