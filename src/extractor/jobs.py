"""In-memory job store for poll fallback (L4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from extractor.events import ProgressEvent

_STAGE_PROGRESS: dict[str, int] = {
    "ingest": 10,
    "schema": 20,
    "extraction": 50,
    "complete": 100,
}


@dataclass
class JobRecord:
    job_id: str
    status: str = "pending"
    stage: str | None = None
    message: str = ""
    progress_pct: int = 0
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "progress_pct": self.progress_pct,
            "result": self.result,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def create(self, job_id: str) -> JobRecord:
        record = JobRecord(job_id=job_id, status="running", message="Starting…")
        self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def update_from_event(self, job_id: str, event: ProgressEvent) -> None:
        record = self._jobs.get(job_id)
        if record is None:
            return
        record.message = event.message
        if event.stage:
            record.stage = event.stage
        record.progress_pct = _progress_for_event(event)
        if event.type == "run_completed":
            record.status = "completed"
            record.progress_pct = 100
            if event.detail and "result" in event.detail:
                record.result = event.detail["result"]
        elif event.type == "run_failed":
            record.status = "failed"
            if event.detail and "result" in event.detail:
                record.result = event.detail["result"]

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        record = self._jobs.get(job_id)
        if record is None:
            return
        record.status = "completed"
        record.progress_pct = 100
        record.result = result


def _progress_for_event(event: ProgressEvent) -> int:
    if event.type == "run_completed":
        return 100
    if event.type == "run_failed":
        return _STAGE_PROGRESS.get(event.stage or "", 50)
    if event.type == "heartbeat" and event.stage == "extraction":
        return 75
    if event.stage in _STAGE_PROGRESS:
        base = _STAGE_PROGRESS[event.stage]
        if event.stage == "extraction" and event.type in {"tool_started", "agent_tool_called"}:
            return min(90, base + 20)
        return base
    return 0


JOB_STORE = JobStore()
