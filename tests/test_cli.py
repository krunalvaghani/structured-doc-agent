"""CLI helpers."""

from __future__ import annotations

import os
from unittest.mock import patch

from extractor.cli import resolve_serve_bind


def test_resolve_serve_bind_defaults_locally() -> None:
    env = {k: v for k, v in os.environ.items() if k not in ("PORT", "EXTRACTOR_PORT", "EXTRACTOR_HOST")}
    with patch.dict(os.environ, env, clear=True):
        host, port = resolve_serve_bind()
    assert host == "127.0.0.1"
    assert port == 8000


def test_resolve_serve_bind_uses_render_port() -> None:
    with patch.dict(os.environ, {"PORT": "10000"}, clear=False):
        host, port = resolve_serve_bind()
    assert host == "0.0.0.0"
    assert port == 10000


def test_resolve_serve_bind_explicit_overrides_env() -> None:
    with patch.dict(os.environ, {"PORT": "10000", "EXTRACTOR_HOST": "0.0.0.0"}, clear=False):
        host, port = resolve_serve_bind(host="10.0.0.1", port=9000)
    assert host == "10.0.0.1"
    assert port == 9000
