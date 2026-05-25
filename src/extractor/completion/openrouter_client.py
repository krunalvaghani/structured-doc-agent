"""OpenRouter chat-completions HTTP client."""

from __future__ import annotations

from typing import Any

import httpx

from extractor.config import OPENROUTER_BASE_URL, Settings


class OpenRouterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        base = settings.anthropic_base_url or OPENROUTER_BASE_URL
        self.base_url = base.rstrip("/")
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

        async with httpx.AsyncClient(timeout=self.settings.request_timeout_s) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return response.json()
