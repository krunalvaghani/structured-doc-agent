"""Shared types for extraction requests and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ExtractionStatus = Literal["success", "partial", "needs_review", "failed"]
ExtractionBackend = Literal["agent", "api"]
ProgressSource = Literal["pipeline", "agent", "tool"]
FieldType = Literal["string", "number", "integer", "float", "boolean", "date", "array"]


@dataclass
class ItemFieldDefinition:
    name: str
    label: str
    type: Literal["string", "number", "integer", "float", "boolean", "date"] = "string"
    description: str | None = None
    required: bool = True

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> ItemFieldDefinition:
        raw_description = item.get("description")
        return cls(
            name=str(item["name"]),
            label=str(item.get("label", item["name"])),
            type=item.get("type", "string"),
            description=str(raw_description).strip() if raw_description else None,
            required=item.get("required", True),
        )


@dataclass
class FieldDefinition:
    name: str
    label: str
    type: FieldType = "string"
    description: str | None = None
    required: bool = True
    item_fields: list[ItemFieldDefinition] | None = None

    @classmethod
    def from_dict(cls, item: dict[str, Any]) -> FieldDefinition:
        item_fields = None
        if item.get("type") == "array":
            raw_items = item.get("item_fields")
            if not isinstance(raw_items, list) or not raw_items:
                raise ValueError(f"array field {item.get('name')!r} requires item_fields")
            item_fields = [ItemFieldDefinition.from_dict(sub) for sub in raw_items]
        raw_description = item.get("description")
        return cls(
            name=str(item["name"]),
            label=str(item.get("label", item["name"])),
            type=item.get("type", "string"),
            description=str(raw_description).strip() if raw_description else None,
            required=item.get("required", True),
            item_fields=item_fields,
        )


@dataclass
class FieldSpec:
    fields: list[FieldDefinition]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FieldSpec:
        raw_fields = data.get("fields")
        if not isinstance(raw_fields, list) or not raw_fields:
            raise ValueError("field_spec must contain a non-empty 'fields' array")

        fields: list[FieldDefinition] = []
        for item in raw_fields:
            if not isinstance(item, dict):
                raise ValueError("each field must be an object")
            fields.append(FieldDefinition.from_dict(item))
        return cls(fields=fields)


@dataclass
class ExtractionOptions:
    model: str | None = None
    schema_model: str | None = None
    max_budget_usd: float | None = None
    backend: ExtractionBackend | None = None


@dataclass
class ExtractionRequest:
    document_path: Path
    field_spec: FieldSpec | None = None
    prompt: str | None = None
    schema: dict[str, Any] | None = None
    options: ExtractionOptions = field(default_factory=ExtractionOptions)
    job_id: str | None = None

    def validate_input_mode(self) -> None:
        modes = sum(
            1 for x in (self.field_spec, self.prompt, self.schema) if x is not None
        )
        if modes != 1:
            raise ValueError("provide exactly one of field_spec, prompt, or schema")


@dataclass
class StageUsage:
    stage: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "model_id": self.model_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": round(self.latency_ms, 1),
        }


@dataclass
class UsageSummary:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0
    by_stage: dict[str, StageUsage] = field(default_factory=dict)
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> UsageSummary:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "by_stage": {k: v.to_dict() for k, v in self.by_stage.items()},
            "by_model": self.by_model,
        }


@dataclass
class ExtractionResult:
    status: ExtractionStatus
    data: dict[str, Any] | None = None
    schema_used: dict[str, Any] | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: UsageSummary = field(default_factory=UsageSummary.empty)
    job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "schema_used": self.schema_used,
            "error": self.error,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "usage": self.usage.to_dict(),
            "job_id": self.job_id,
        }
