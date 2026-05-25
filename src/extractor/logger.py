"""Central logging for the extractor package."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, TextIO

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_ROOT_LOGGER_NAME = "extractor"
_ENV_LOG_LEVEL = "LOG_LEVEL"

_configured = False


def _default_stream() -> TextIO:
    """Use stdout on PaaS (Render sets PORT) so log aggregators capture output reliably."""
    if os.environ.get("PORT"):
        return sys.stdout
    return sys.stderr


def _parse_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    normalized = level.strip().upper()
    if normalized.isdigit():
        return int(normalized)
    numeric = getattr(logging, normalized, None)
    if isinstance(numeric, int):
        return numeric
    raise ValueError(f"Invalid log level: {level!r}")


def resolve_log_level(level: str | int | None = None) -> str:
    """Return normalized log level name (e.g. ``INFO``)."""
    if level is None:
        level = os.environ.get(_ENV_LOG_LEVEL, "INFO")
    return logging.getLevelName(_parse_level(level))


def configure_logging(
    *,
    level: str | int | None = None,
    stream: TextIO | None = None,
    log_format: str = _DEFAULT_FORMAT,
    date_format: str = _DEFAULT_DATE_FORMAT,
    force: bool = False,
) -> None:
    """Configure handlers and format for all ``extractor.*`` loggers."""
    global _configured
    if _configured and not force:
        return

    level_name = resolve_log_level(level)
    numeric_level = _parse_level(level_name)

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(numeric_level)
    root.handlers.clear()

    handler = logging.StreamHandler(stream or _default_stream())
    handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(handler)
    root.propagate = False

    _configured = True


def uvicorn_log_config(level: str | int | None = None) -> dict[str, Any]:
    """Logging dict for ``uvicorn.run(log_config=...)`` aligned with extractor format."""
    level_name = resolve_log_level(level)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "extractor": {
                "format": _DEFAULT_FORMAT,
                "datefmt": _DEFAULT_DATE_FORMAT,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "extractor",
                "stream": _default_stream(),
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": level_name, "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": level_name, "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": level_name, "propagate": False},
        },
    }


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the ``extractor`` namespace."""
    if not _configured:
        configure_logging()

    if name is None or name == "":
        return logging.getLogger(_ROOT_LOGGER_NAME)
    if name == _ROOT_LOGGER_NAME or name.startswith(f"{_ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
