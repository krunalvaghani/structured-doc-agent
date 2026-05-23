"""Tests for progress emitter and job store."""

from __future__ import annotations

import asyncio

import pytest

from extractor.events import ProgressEmitter, pipeline_event
from extractor.jobs import JOB_STORE, JobStore


@pytest.mark.asyncio
async def test_emitter_subscribe_receives_events() -> None:
    emitter = ProgressEmitter()
    events = []

    async def consume() -> None:
        async for event in emitter.subscribe():
            events.append(event)

    task = asyncio.create_task(consume())
    await emitter.emit(pipeline_event("run_started", "Starting…"))
    await emitter.emit(pipeline_event("file_validated", "OK", stage="ingest"))
    await emitter.close()
    await task

    assert len(events) == 2
    assert events[0].source == "pipeline"
    assert events[0].type == "run_started"


def test_job_store_progress_pct() -> None:
    store = JobStore()
    store.create("job1")
    store.update_from_event(
        "job1",
        pipeline_event("file_validated", "Validated", stage="ingest"),
    )
    record = store.get("job1")
    assert record is not None
    assert record.progress_pct == 10
    assert record.stage == "ingest"
