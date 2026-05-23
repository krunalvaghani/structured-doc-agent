"""Convert UI field specs to JSON Schema for structured output."""

from __future__ import annotations

import re
from typing import Any

from extractor.types import FieldDefinition, FieldSpec

FIELD_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")

MAX_SCALAR_FIELDS = 20
MAX_ARRAY_GROUPS = 1
MAX_ITEM_FIELDS = 10

_JSON_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "integer": "integer",
    "float": "number",
    "boolean": "boolean",
    "date": "string",
    "array": "array",
}

_ALLOWED_SCALAR_TYPES = frozenset({"string", "number", "integer", "float", "boolean", "date"})

_NULL_HINT = " Return null if not explicitly present in the document."
_EMPTY_LIST_HINT = " Use an empty array if no rows exist. Do not invent rows."


def _scalar_schema(field_type: str, *, nullable: bool = True) -> dict[str, Any]:
    base_type = _JSON_TYPE_MAP.get(field_type, "string")
    schema: dict[str, Any] = (
        {"type": [base_type, "null"]} if nullable else {"type": base_type}
    )
    if field_type == "date":
        schema["format"] = "date"
    return schema


def _schema_description(label: str, description: str | None, *, null_hint: bool = True) -> str:
    label = label.strip()
    desc = (description or "").strip()
    if desc and label:
        text = f"{label}: {desc}"
    else:
        text = desc or label
    if null_hint:
        text += _NULL_HINT
    return text


def _validate_field_name(name: str, *, context: str) -> None:
    if not FIELD_NAME_RE.match(name):
        raise ValueError(
            f"{context} {name!r} is invalid — use letters, numbers, underscore, dot, "
            f"or hyphen only (max 64 chars), e.g. company_name"
        )


def validate_field_spec(spec: FieldSpec) -> None:
    if not spec.fields:
        raise ValueError("field_spec must contain at least one field")
    if len(spec.fields) > MAX_SCALAR_FIELDS + MAX_ARRAY_GROUPS:
        raise ValueError(f"too many fields (max {MAX_SCALAR_FIELDS + MAX_ARRAY_GROUPS})")

    names: set[str] = set()
    array_count = 0
    for field in spec.fields:
        name = field.name.strip()
        label = field.label.strip()
        if not name:
            raise ValueError("field name must not be empty")
        if not label:
            raise ValueError(f"field {name!r} label must not be empty")
        if name in names:
            raise ValueError(f"duplicate field name: {name!r}")
        names.add(name)
        _validate_field_name(name, context="field name")

        if field.type != "array" and field.type not in _ALLOWED_SCALAR_TYPES:
            raise ValueError(f"field {name!r} has unsupported type {field.type!r}")

        if field.type == "array":
            array_count += 1
            if array_count > MAX_ARRAY_GROUPS:
                raise ValueError(f"at most {MAX_ARRAY_GROUPS} array field allowed in v1")
            if not field.item_fields:
                raise ValueError(f"array field {name!r} requires item_fields")
            if len(field.item_fields) > MAX_ITEM_FIELDS:
                raise ValueError(f"array field {name!r} has too many item_fields")
            item_names: set[str] = set()
            for item in field.item_fields:
                item_name = item.name.strip()
                if not item_name:
                    raise ValueError(f"item field name empty in {name!r}")
                if item_name in item_names:
                    raise ValueError(f"duplicate item field {item_name!r} in {name!r}")
                item_names.add(item_name)
                _validate_field_name(item_name, context="list column name")
                if item.type not in _ALLOWED_SCALAR_TYPES:
                    raise ValueError(
                        f"list column {item_name!r} in {name!r} has unsupported type {item.type!r}"
                    )


def field_spec_to_json_schema(spec: FieldSpec) -> dict[str, Any]:
    """Build JSON Schema object for Claude Agent SDK output_format."""
    validate_field_spec(spec)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for field in spec.fields:
        required.append(field.name.strip())
        if field.type == "array":
            assert field.item_fields is not None
            item_props: dict[str, Any] = {}
            item_required: list[str] = []
            for item in field.item_fields:
                item_schema = _scalar_schema(item.type)
                item_schema["description"] = _schema_description(item.label, item.description)
                item_props[item.name] = item_schema
                item_required.append(item.name)
            list_desc = _schema_description(field.label, field.description, null_hint=False)
            properties[field.name] = {
                "type": "array",
                "description": list_desc + _EMPTY_LIST_HINT,
                "items": {
                    "type": "object",
                    "properties": item_props,
                    "required": item_required,
                    "additionalProperties": False,
                },
            }
        else:
            properties[field.name] = {
                **_scalar_schema(field.type),
                "description": _schema_description(field.label, field.description),
            }

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def describe_field_spec(spec: FieldSpec) -> str:
    """Human-readable summary for progress events."""
    scalar = sum(1 for f in spec.fields if f.type != "array")
    arrays = [f for f in spec.fields if f.type == "array"]
    parts = [f"{scalar} field(s)"]
    if arrays:
        parts.append(f"{arrays[0].name} list")
    return " + ".join(parts)
