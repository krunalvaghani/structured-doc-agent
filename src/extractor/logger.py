"""Central logging for the extractor package."""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_ROOT_LOGGER_NAME = "extractor"
_ENV_LOG_LEVEL = "LOG_LEVEL"

_configured = False


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

    if level is None:
        level = os.environ.get(_ENV_LOG_LEVEL, "INFO")

    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(_parse_level(level))
    root.handlers.clear()

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    root.addHandler(handler)
    root.propagate = False

    _configured = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the ``extractor`` namespace."""
    if not _configured:
        configure_logging()

    if name is None or name == "":
        return logging.getLogger(_ROOT_LOGGER_NAME)
    if name == _ROOT_LOGGER_NAME or name.startswith(f"{_ROOT_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
