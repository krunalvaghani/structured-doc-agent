"""Map Claude SDK stream messages to progress events."""

from __future__ import annotations

import time
from typing import Any

from extractor.cost import stage_to_summary, usage_from_result_message
from extractor.events import ProgressEmitter, ProgressEvent
from extractor.types import UsageSummary

try:
    from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent
except ImportError:  # pragma: no cover
    AssistantMessage = ResultMessage = StreamEvent = Any  # type: ignore[misc,assignment]


class AgentStreamAdapter:
    def __init__(
        self,
        emitter: ProgressEmitter,
        *,
        stage: str = "extraction",
        model_id: str = "unknown",
        trust_sdk_cost: bool = True,
    ) -> None:
        self.emitter = emitter
        self.stage = stage
        self.model_id = model_id
        self.trust_sdk_cost = trust_sdk_cost
        self.seen_message_ids: set[str] = set()
        self.agent_event_count = 0
        self._stage_start = time.monotonic()

    async def handle_message(self, message: Any) -> UsageSummary | None:
        if isinstance(message, AssistantMessage):
            await self._handle_assistant(message)
            return None
        if isinstance(message, StreamEvent):
            await self._handle_stream(message)
            return None
        if isinstance(message, ResultMessage):
            return await self._handle_result(message)
        return None

    async def _handle_assistant(self, message: AssistantMessage) -> None:
        msg_id = getattr(message, "message_id", None) or id(message)
        if msg_id in self.seen_message_ids:
            return
        self.seen_message_ids.add(str(msg_id))

        content = getattr(message, "content", None) or []
        for block in content:
            if hasattr(block, "name"):
                self.agent_event_count += 1
                await self.emitter.emit(
                    ProgressEvent(
                        type="agent_tool_called",
                        source="agent",
                        stage=self.stage,
                        message=f"Claude calling {block.name}",
                        detail={
                            "tool": block.name,
                            "input": getattr(block, "input", None),
                        },
                    )
                )
            elif hasattr(block, "text") and block.text:
                self.agent_event_count += 1
                await self.emitter.emit(
                    ProgressEvent(
                        type="agent_text",
                        source="agent",
                        stage=self.stage,
                        message=block.text[:200],
                        detail={"truncated": len(block.text) > 200},
                    )
                )

    async def _handle_stream(self, message: StreamEvent) -> None:
        event = getattr(message, "event", None) or {}
        if event.get("type") != "content_block_delta":
            return
        delta = event.get("delta") or {}
        if delta.get("type") != "text_delta":
            return
        text = delta.get("text") or ""
        if not text.strip():
            return
        self.agent_event_count += 1
        await self.emitter.emit(
            ProgressEvent(
                type="agent_text_delta",
                source="agent",
                stage=self.stage,
                message=text,
            )
        )

    async def _handle_result(self, message: ResultMessage) -> UsageSummary:
        latency_ms = (time.monotonic() - self._stage_start) * 1000
        stage_usage = usage_from_result_message(
            message,
            stage=self.stage,
            model_id=self.model_id,
            latency_ms=latency_ms,
            trust_sdk_cost=self.trust_sdk_cost,
        )
        summary = stage_to_summary(stage_usage)
        summary.by_model = {
            self.model_id: {
                "input_tokens": stage_usage.input_tokens,
                "output_tokens": stage_usage.output_tokens,
                "cost_usd": round(stage_usage.cost_usd, 6),
            }
        }
        await self.emitter.emit(
            ProgressEvent(
                type="agent_stage_result",
                source="agent",
                stage=self.stage,
                message=f"Agent finished ({message.subtype})",
                detail={
                    "subtype": message.subtype,
                    "cost_usd": stage_usage.cost_usd,
                },
            )
        )
        return summary
