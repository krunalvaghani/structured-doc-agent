"""NL prompt to JSON Schema via Haiku."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from extractor.agent.prompts import SCHEMA_PLANNER_SYSTEM_PROMPT
from extractor.agent.stream_adapter import AgentStreamAdapter
from extractor.config import Settings
from extractor.events import ProgressEmitter, pipeline_event
from extractor.types import UsageSummary

PLANNER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "json_schema": {
            "type": "object",
            "description": "JSON Schema for extraction output",
        }
    },
    "required": ["json_schema"],
    "additionalProperties": False,
}


async def plan_schema_from_prompt(
    prompt: str,
    *,
    settings: Settings,
    emitter: ProgressEmitter,
    model: str | None = None,
    timeout_s: int | None = None,
) -> tuple[dict[str, Any], UsageSummary]:
    model_id = settings.resolve_model(model, default=settings.schema_model)
    await emitter.emit(
        pipeline_event("schema_plan_started", "Planning schema from prompt…", stage="schema")
    )

    options = ClaudeAgentOptions(
        model=model_id,
        system_prompt=SCHEMA_PLANNER_SYSTEM_PROMPT,
        permission_mode="dontAsk",
        output_format={"type": "json_schema", "schema": PLANNER_OUTPUT_SCHEMA},
        env=settings.agent_sdk_env() if settings.llm_configured else dict(os.environ),
    )
    adapter = AgentStreamAdapter(
        emitter,
        stage="schema_planner",
        model_id=model_id,
        trust_sdk_cost=not settings.use_openrouter,
    )
    usage = UsageSummary.empty()
    schema: dict[str, Any] | None = None

    async def _run() -> None:
        nonlocal schema, usage
        async for message in query(
            prompt=f"Design a JSON Schema for this extraction request:\n\n{prompt}",
            options=options,
        ):
            stage_usage = await adapter.handle_message(message)
            if stage_usage is not None:
                usage = stage_usage
            if isinstance(message, ResultMessage):
                if message.subtype == "success" and message.structured_output:
                    raw = message.structured_output.get("json_schema")
                    if isinstance(raw, dict):
                        schema = raw

    await asyncio.wait_for(_run(), timeout=timeout_s or settings.request_timeout_s)

    if schema is None:
        raise RuntimeError("schema planner did not return json_schema")

    await emitter.emit(
        pipeline_event(
            "schema_planned",
            f"Schema planned ({len(schema.get('properties', {}))} top-level fields)",
            stage="schema",
            detail={"properties": list(schema.get("properties", {}).keys())},
        )
    )
    return schema, usage
