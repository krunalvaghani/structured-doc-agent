"""Validate extraction JSON against the run schema."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError


def _format_validation_error(err: ValidationError) -> str:
    parts = [str(p) for p in err.absolute_path]
    location = ".".join(parts) if parts else "(root)"
    return f"{location}: {err.message}"


def validation_errors(data: Any, schema: dict[str, Any], *, limit: int = 25) -> list[str]:
    """Return human-readable schema violations; empty list means valid."""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    return [_format_validation_error(err) for err in errors[:limit]]


def is_valid_extraction_data(data: Any, schema: dict[str, Any]) -> bool:
    return not validation_errors(data, schema)
