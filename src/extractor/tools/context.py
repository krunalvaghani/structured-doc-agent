"""Per-job context for MCP tools.

Uses contextvars so each asyncio task (i.e. each concurrent request) has its
own isolated ToolContext — no cross-request contamination even when multiple
extractions run at the same time.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from extractor.events import ProgressEmitter
from extractor.security import PathGuard


@dataclass
class ToolContext:
    job_root: Path
    document_path: Path
    emitter: ProgressEmitter
    path_guard: PathGuard


_TOOL_CONTEXT: ContextVar[ToolContext | None] = ContextVar("_TOOL_CONTEXT", default=None)


def set_tool_context(ctx: ToolContext) -> None:
    _TOOL_CONTEXT.set(ctx)


def get_tool_context() -> ToolContext:
    ctx = _TOOL_CONTEXT.get()
    if ctx is None:
        raise RuntimeError("tool context not initialized")
    return ctx


def clear_tool_context() -> None:
    _TOOL_CONTEXT.set(None)
