"""OpenRouter chat-completions HTTP client."""

from __future__ import annotations

from typing import Any

import httpx

from extractor.config import OPENROUTER_BASE_URL, Settings
from extractor.logger import get_logger

log = get_logger(__name__)


def normalize_openrouter_base_url(base: str) -> str:
    """Return base URL for appending ``/v1/chat/completions`` (avoid double ``/v1``)."""
    cleaned = base.rstrip("/")
    if cleaned.endswith("/v1"):
        return cleaned[: -len("/v1")]
    return cleaned


def chat_completions_url(base: str) -> str:
    return f"{normalize_openrouter_base_url(base)}/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        base = settings.anthropic_base_url or OPENROUTER_BASE_URL
        self.base_url = normalize_openrouter_base_url(base)
        self.api_key = settings.openrouter_api_key or ""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/krunalvaghani/structured-doc-agent",
            "X-Title": "structured-doc-agent",
        }

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
        response_format: dict[str, Any] | None = None,
        plugins: list[dict[str, Any]] | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": self.settings.max_output_tokens,
            "stream": False,
        }
        if tools is not None:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if response_format is not None:
            payload["response_format"] = response_format
        if plugins is not None:
            payload["plugins"] = plugins
        if reasoning is not None:
            payload["reasoning"] = reasoning

        url = chat_completions_url(self.base_url)
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            response = await client.post(
                url,
                headers=self._headers(),
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _format_http_error(exc, model=model, url=url)
                raise httpx.HTTPStatusError(
                    detail,
                    request=exc.request,
                    response=exc.response,
                ) from exc
            return response.json()


def _format_http_error(exc: httpx.HTTPStatusError, *, model: str, url: str) -> str:
    body = exc.response.text.strip()
    message = body
    try:
        data = exc.response.json()
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            message = str(err["message"])
        elif isinstance(err, str):
            message = err
    except Exception:
        pass
    return (
        f"OpenRouter HTTP {exc.response.status_code} for model {model!r}: {message} "
        f"(url={url})"
    )
