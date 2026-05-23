"""Progress events and emitter for dual-source SSE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from extractor.types import ProgressSource

ProgressEventType = Literal[
    "run_started",
    "file_received",
    "file_validated",
    "schema_build_started",
    "schema_built",
    "schema_plan_started",
    "schema_planned",
    "stage_started",
    "stage_completed",
    "tool_started",
    "tool_completed",
    "agent_tool_called",
    "agent_tool_result",
    "agent_text",
    "agent_text_delta",
    "agent_stage_result",
    "agent_stream_warning",
    "usage_ready",
    "heartbeat",
    "verification_warnings",
    "run_completed",
    "run_failed",
]


@dataclass
class ProgressEvent:
    type: str
    source: ProgressSource
    message: str
    stage: str | None = None
    detail: dict[str, Any] | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_sse(self) -> str:
        return f"data: {json.dumps(self.to_dict())}\n\n"


def pipeline_event(
    event_type: ProgressEventType,
    message: str,
    *,
    stage: str | None = None,
    detail: dict[str, Any] | None = None,
) -> ProgressEvent:
    return ProgressEvent(
        type=event_type,
        source="pipeline",
        message=message,
        stage=stage,
        detail=detail,
    )


class ProgressEmitter:
    """In-memory async queue per job for SSE subscribers."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ProgressEvent | None] = asyncio.Queue()
        self._closed = False
        self.events: list[ProgressEvent] = []

    async def emit(self, event: ProgressEvent) -> None:
        if self._closed:
            return
        self.events.append(event)
        await self._queue.put(event)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._queue.put(None)

    async def subscribe(self) -> AsyncIterator[ProgressEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event
