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
