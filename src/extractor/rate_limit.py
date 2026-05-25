"""Per-IP and global daily extraction rate limits."""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request

from extractor.config import Settings


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    scope: str  # "ip" | "global"
    message: str
    retry_after_seconds: int
    quota: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": "rate_limit_exceeded",
            "scope": self.scope,
            "message": self.message,
            "retry_after_seconds": self.retry_after_seconds,
            "quota": self.quota,
        }


def client_ip(request: Request) -> str:
    """Resolve client IP; trust X-Forwarded-For leftmost (Render / reverse proxy)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _utc_midnight_next() -> datetime:
    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).date()
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=UTC)


class ExtractionRateLimiter:
    """In-memory per-IP sliding window + global daily counter."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._ip_events: dict[str, deque[float]] = defaultdict(deque)
        self._global_date: str | None = None
        self._global_count: int = 0

    @property
    def enabled(self) -> bool:
        return self._settings.rate_limit_enabled

    def _prune_ip(self, ip: str, *, now: float, window: float) -> deque[float]:
        events = self._ip_events[ip]
        cutoff = now - window
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def _reset_global_if_needed(self, today: str) -> None:
        if self._global_date != today:
            self._global_date = today
            self._global_count = 0

    def _snapshot_unlocked(self, ip: str, *, now: float | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False}

        now = now if now is not None else datetime.now(UTC).timestamp()
        window = float(self._settings.rate_limit_per_ip_window_seconds)
        limit_ip = self._settings.rate_limit_per_ip
        limit_global = self._settings.rate_limit_global_daily
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        self._reset_global_if_needed(today)

        events = self._prune_ip(ip, now=now, window=window)
        used_ip = len(events)
        used_global = self._global_count
        remaining_ip = max(0, limit_ip - used_ip)
        remaining_global = max(0, limit_global - used_global)

        retry_ip = 0
        if events and used_ip >= limit_ip:
            retry_ip = max(1, int(math.ceil(events[0] + window - now)))

        return {
            "enabled": True,
            "remaining_ip": remaining_ip,
            "limit_ip": limit_ip,
            "window_seconds": int(window),
            "remaining_global": remaining_global,
            "limit_global_daily": limit_global,
            "resets_global_at": _utc_midnight_next().isoformat().replace("+00:00", "Z"),
            "retry_after_seconds_ip": retry_ip,
        }

    def snapshot(self, ip: str) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked(ip)

    def check_and_consume(self, ip: str) -> None:
        if not self.enabled:
            return

        now = datetime.now(UTC).timestamp()
        window = float(self._settings.rate_limit_per_ip_window_seconds)
        limit_ip = self._settings.rate_limit_per_ip
        limit_global = self._settings.rate_limit_global_daily
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        with self._lock:
            self._reset_global_if_needed(today)
            quota = self._snapshot_unlocked(ip, now=now)

            if self._global_count >= limit_global:
                midnight = _utc_midnight_next()
                retry = max(1, int(math.ceil(midnight.timestamp() - now)))
                raise RateLimitExceeded(
                    scope="global",
                    message=(
                        f"Daily demo limit reached ({limit_global} extractions per day). "
                        "Try again after UTC midnight."
                    ),
                    retry_after_seconds=retry,
                    quota=quota,
                )

            events = self._prune_ip(ip, now=now, window=window)
            if len(events) >= limit_ip:
                retry = max(1, int(math.ceil(events[0] + window - now)))
                minutes = max(1, int(math.ceil(retry / 60)))
                raise RateLimitExceeded(
                    scope="ip",
                    message=(
                        f"Hourly limit reached ({limit_ip} extractions per hour). "
                        f"Try again in about {minutes} minute(s)."
                    ),
                    retry_after_seconds=retry,
                    quota=quota,
                )

            events.append(now)
            self._global_count += 1


_limiter: ExtractionRateLimiter | None = None
_limiter_key: tuple[bool, int, int, int] | None = None


def _rate_limit_settings_key(settings: Settings) -> tuple[bool, int, int, int]:
    return (
        settings.rate_limit_enabled,
        settings.rate_limit_per_ip,
        settings.rate_limit_per_ip_window_seconds,
        settings.rate_limit_global_daily,
    )


def get_rate_limiter(settings: Settings | None = None) -> ExtractionRateLimiter:
    global _limiter, _limiter_key
    from extractor.config import get_settings

    settings = settings or get_settings()
    key = _rate_limit_settings_key(settings)
    if _limiter is None or _limiter_key != key:
        _limiter = ExtractionRateLimiter(settings)
        _limiter_key = key
    return _limiter


def reset_rate_limiter_for_tests() -> None:
    """Clear singleton state between tests."""
    global _limiter, _limiter_key
    _limiter = None
    _limiter_key = None
