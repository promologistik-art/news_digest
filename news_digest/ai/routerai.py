"""Async client for RouterAI's OpenAI-compatible Chat Completions API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Self

import httpx

from news_digest.config import Settings

logger = logging.getLogger(__name__)


class RouterAIError(RuntimeError):
    """Sanitized RouterAI request or response error."""


@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cached_prompt_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ChatResult:
    content: str
    model: str
    provider: str | None
    request_id: str | None
    usage: TokenUsage | None
    raw: Mapping[str, Any]


class RouterAIClient:
    """Small dependency-light client; API keys are never included in logs/errors."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = settings.ai_base_url.rstrip("/")
        self.api_key = settings.routerai_api_key.get_secret_value()
        self.model = settings.ai_model
        self.timeout = settings.ai_timeout_seconds
        self.max_retries = settings.ai_max_retries
        self._client = http_client
        self._owns_client = http_client is None

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        operation: str = "chat",
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Mapping[str, Any] | None = None,
    ) -> ChatResult:
        if not self.api_key:
            raise RouterAIError("ROUTERAI_API_KEY is not configured.")
        if not messages:
            raise ValueError("messages must contain at least one message")

        payload: dict[str, Any] = {"model": self.model, "messages": list(messages)}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = dict(response_format)

        client = self._client
        temporary_client = client is None
        if temporary_client:
            client = httpx.AsyncClient(timeout=self.timeout)

        assert client is not None
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Title": "news_digest",
        }
        last_error: Exception | None = None
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    if (response.status_code == 429 or response.status_code >= 500) and attempt < self.max_retries:
                        await asyncio.sleep(min(2 ** attempt, 8))
                        continue
                    if response.is_error:
                        # Do not echo response body: gateways may include request metadata.
                        raise RouterAIError(
                            f"RouterAI returned HTTP {response.status_code} "
                            f"for operation '{operation}'."
                        )
                    try:
                        data = response.json()
                    except ValueError as exc:
                        raise RouterAIError("RouterAI returned invalid JSON.") from exc
                    return self._parse_result(data, response.headers.get("x-request-id"))
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        break
                    await asyncio.sleep(min(2 ** attempt, 8))
                except RouterAIError:
                    raise
            raise RouterAIError(
                f"RouterAI request failed after {self.max_retries + 1} attempts "
                f"({type(last_error).__name__ if last_error else 'temporary server error'})."
            ) from last_error
        finally:
            if temporary_client:
                await client.aclose()

    def _parse_result(
        self,
        data: Any,
        request_id_header: str | None,
    ) -> ChatResult:
        if not isinstance(data, dict):
            raise RouterAIError("RouterAI response must be a JSON object.")
        try:
            choices = data["choices"]
            message = choices[0]["message"]
            content = message.get("content")
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            model = str(data.get("model") or self.model)
        except (KeyError, IndexError, TypeError) as exc:
            raise RouterAIError("RouterAI response has an unexpected Chat Completions shape.") from exc

        usage_data = data.get("usage")
        usage = None
        if isinstance(usage_data, dict):
            prompt_details = usage_data.get("prompt_tokens_details") or {}
            cached_tokens = _optional_int(
                prompt_details.get("cached_tokens")
                if isinstance(prompt_details, dict)
                else None
            )
            if cached_tokens is None:
                cached_tokens = _optional_int(usage_data.get("cache_read_input_tokens"))
            usage = TokenUsage(
                prompt_tokens=_optional_int(usage_data.get("prompt_tokens")),
                completion_tokens=_optional_int(usage_data.get("completion_tokens")),
                total_tokens=_optional_int(usage_data.get("total_tokens")),
                cached_prompt_tokens=cached_tokens,
            )
        provider = data.get("provider")
        return ChatResult(
            content=content,
            model=model,
            provider=str(provider) if provider else None,
            request_id=str(data.get("id") or request_id_header) if (
                data.get("id") or request_id_header
            ) else None,
            usage=usage,
            raw=data,
        )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
