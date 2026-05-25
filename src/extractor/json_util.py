"""Parse JSON from agent result text."""

from __future__ import annotations

import json
import re
from typing import Any

_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def parse_json_text(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty response")

    fence = _JSON_FENCE_RE.search(stripped)
    payload = fence.group(1).strip() if fence else stripped

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        start = payload.find("{")
        end = payload.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(payload[start : end + 1])


def _text_from_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind == "text":
                parts.append(part.get("text") or "")
            elif kind == "json" and part.get("json") is not None:
                return json.dumps(part["json"])
        return "".join(parts)
    return str(content)


def _reasoning_text(message: dict[str, Any]) -> str:
    parts: list[str] = []
    reasoning = message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        parts.append(reasoning.strip())
    details = message.get("reasoning_details")
    if isinstance(details, list):
        for item in details:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def parse_assistant_json(message: dict[str, Any]) -> Any:
    """Parse structured JSON from an OpenRouter/OpenAI assistant message."""
    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return parsed
    if parsed is not None and not isinstance(parsed, str):
        return parsed

    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal.strip():
        raise ValueError(f"model refused: {refusal.strip()[:200]}")

    content_text = _text_from_message_content(message.get("content"))
    if content_text.strip():
        try:
            return parse_json_text(content_text)
        except (ValueError, json.JSONDecodeError):
            pass

    reasoning_text = _reasoning_text(message)
    if reasoning_text.strip():
        return parse_json_text(reasoning_text)

    if content_text.strip():
        raise ValueError("could not parse JSON from assistant content")
    raise ValueError("empty assistant response")
