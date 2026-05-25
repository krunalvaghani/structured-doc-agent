"""Logging configuration tests."""

from __future__ import annotations

import logging
import os
from io import StringIO
from unittest.mock import patch

from extractor.logger import configure_logging, get_logger, resolve_log_level, uvicorn_log_config


def test_get_logger_uses_extractor_namespace() -> None:
    configure_logging(level="INFO", stream=StringIO(), force=True)
    logger = get_logger("extractor.api")
    assert logger.name == "extractor.api"


def test_resolve_log_level_from_env() -> None:
    with patch.dict(os.environ, {"LOG_LEVEL": "debug"}, clear=False):
        assert resolve_log_level() == "DEBUG"


def test_uvicorn_log_config_includes_access_logger() -> None:
    config = uvicorn_log_config("INFO")
    assert "uvicorn.access" in config["loggers"]
    assert config["loggers"]["uvicorn.access"]["level"] == "INFO"


def test_log_message_reaches_handler() -> None:
    stream = StringIO()
    configure_logging(level="INFO", stream=stream, force=True)
    get_logger(__name__).info("hello from test")
    assert "hello from test" in stream.getvalue()
    assert "INFO" in stream.getvalue()


def test_default_stream_stdout_when_port_set() -> None:
    with patch.dict(os.environ, {"PORT": "10000"}, clear=False):
        config = uvicorn_log_config("INFO")
        assert config["handlers"]["default"]["stream"] is not None
