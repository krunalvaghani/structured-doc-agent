"""OpenRouter / Anthropic model registry — single source for IDs, labels, and pricing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    """One selectable extraction model."""

    id: str
    label: str
    openrouter_slug: str
    anthropic_id: str | None = None
    input_per_m: float = 3.0
    output_per_m: float = 15.0
    vision: bool = False
    openrouter_only: bool = False
    agent_sdk_compatible: bool = True

    def api_model_id(self, *, use_openrouter: bool) -> str:
        if use_openrouter:
            return self.openrouter_slug
        if self.anthropic_id:
            return self.anthropic_id
        return self.openrouter_slug

    def to_dict(self, *, use_openrouter: bool) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "slug": self.api_model_id(use_openrouter=use_openrouter),
            "vision": self.vision,
            "input_per_m": self.input_per_m,
            "output_per_m": self.output_per_m,
            "agent_sdk_compatible": self.agent_sdk_compatible,
        }


# OpenRouter list prices (USD per 1M tokens) — override via OPENROUTER_PRICING_JSON / ANTHROPIC_PRICING_JSON
MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="deepseek-v3.2",
        label="DeepSeek V3.2",
        openrouter_slug="deepseek/deepseek-v3.2",
        input_per_m=0.252,
        output_per_m=0.378,
        openrouter_only=True,
    ),
    ModelSpec(
        id="deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        openrouter_slug="deepseek/deepseek-v4-pro",
        input_per_m=0.435,
        output_per_m=0.87,
        openrouter_only=True,
    ),
    ModelSpec(
        id="kimi-k2.6",
        label="Kimi K2.6",
        openrouter_slug="moonshotai/kimi-k2.6",
        input_per_m=0.95,
        output_per_m=4.0,
        vision=True,
        openrouter_only=True,
    ),
    ModelSpec(
        id="gemini-2.5-flash",
        label="Gemini 2.5 Flash",
        openrouter_slug="google/gemini-2.5-flash",
        input_per_m=0.30,
        output_per_m=2.50,
        vision=True,
        openrouter_only=True,
    ),
    ModelSpec(
        id="claude-sonnet-4-6",
        label="Claude Sonnet 4.6",
        openrouter_slug="anthropic/claude-sonnet-4.6",
        anthropic_id="claude-sonnet-4-6",
        input_per_m=3.0,
        output_per_m=15.0,
        vision=True,
    ),
    ModelSpec(
        id="claude-haiku-4-5-20251001",
        label="Claude Haiku 4.5 (fast/cheap)",
        openrouter_slug="anthropic/claude-haiku-4.5",
        anthropic_id="claude-haiku-4-5-20251001",
        input_per_m=1.0,
        output_per_m=5.0,
    ),
)

_MODEL_BY_ID: dict[str, ModelSpec] = {m.id: m for m in MODELS}
_MODEL_BY_SLUG: dict[str, ModelSpec] = {}
for _m in MODELS:
    _MODEL_BY_SLUG[_m.openrouter_slug] = _m
    if _m.anthropic_id:
        _MODEL_BY_SLUG[_m.anthropic_id] = _m

DEFAULT_MODEL_ID = "claude-haiku-4-5-20251001"
DEFAULT_OPENROUTER_MODEL_ID = "kimi-k2.6"
VISION_FALLBACK_MODEL_ID = "kimi-k2.6"
ANTHROPIC_VISION_FALLBACK_MODEL_ID = "claude-sonnet-4-6"

# Reliable OpenRouter fallbacks when the selected model cannot complete structured output.
# Used by completion_model_fallback_chain() — see ARCHITECTURE.md §6 and README.md.
COMPLETION_FALLBACK_MODEL_IDS: tuple[str, ...] = (
    DEFAULT_OPENROUTER_MODEL_ID,
    "gemini-2.5-flash",
    "claude-haiku-4-5-20251001",
)


def models_for_provider(provider: str | None) -> list[ModelSpec]:
    if provider == "anthropic":
        return [m for m in MODELS if not m.openrouter_only]
    return list(MODELS)


def get_model(model_id: str | None) -> ModelSpec | None:
    if not model_id:
        return None
    if model_id in _MODEL_BY_ID:
        return _MODEL_BY_ID[model_id]
    return _MODEL_BY_SLUG.get(model_id)


def resolve_model_id(
    model_id: str | None,
    *,
    use_openrouter: bool,
    default: str,
) -> str:
    raw = model_id or default
    spec = get_model(raw)
    if spec:
        return spec.api_model_id(use_openrouter=use_openrouter)
    if use_openrouter and "/" in raw:
        return raw
    return raw


def pricing_for_model(model_id: str) -> tuple[float, float]:
    spec = get_model(model_id)
    if spec:
        return spec.input_per_m, spec.output_per_m
    lower = model_id.lower()
    if "haiku" in lower:
        return 1.0, 5.0
    if "kimi" in lower:
        return 0.95, 4.0
    if "gemini" in lower and "flash" in lower:
        return 0.30, 2.50
    if "deepseek" in lower and "v3" in lower:
        return 0.252, 0.378
    if "deepseek" in lower:
        return 0.435, 0.87
    if "sonnet" in lower:
        return 3.0, 15.0
    if "opus" in lower:
        return 15.0, 75.0
    return 3.0, 15.0


def model_short_label(model_id: str) -> str:
    spec = get_model(model_id)
    if spec:
        return spec.id.split("/")[-1] if "/" in spec.id else spec.id
    if "/" in model_id:
        return model_id.split("/")[-1]
    return model_id


@dataclass(frozen=True)
class ExtractionModelChoice:
    """Resolved extraction model after optional vision fallback."""

    requested_id: str
    effective_id: str
    resolved_slug: str
    label: str
    requested_label: str
    vision_fallback: bool
    needs_vision: bool


def _vision_fallback_id(*, use_openrouter: bool, vision_model: str | None) -> str:
    if vision_model:
        spec = get_model(vision_model)
        if spec and (use_openrouter or not spec.openrouter_only):
            return spec.id
    return VISION_FALLBACK_MODEL_ID if use_openrouter else ANTHROPIC_VISION_FALLBACK_MODEL_ID


def _model_label(registry_id: str, *, use_openrouter: bool, default: str) -> str:
    resolved = resolve_model_id(registry_id, use_openrouter=use_openrouter, default=default)
    spec = get_model(registry_id) or get_model(resolved)
    return spec.label if spec else model_short_label(resolved)


def pick_extraction_model(
    *,
    needs_vision: bool,
    model_option: str | None,
    use_openrouter: bool,
    default_model: str,
    vision_model: str | None = None,
) -> ExtractionModelChoice:
    requested_id = model_option or default_model
    requested_resolved = resolve_model_id(
        model_option, use_openrouter=use_openrouter, default=default_model
    )
    requested_spec = get_model(requested_id) or get_model(requested_resolved)
    requested_label = _model_label(requested_id, use_openrouter=use_openrouter, default=default_model)

    effective_id = requested_id
    vision_fallback = False

    if needs_vision and (requested_spec is None or not requested_spec.vision):
        effective_id = _vision_fallback_id(use_openrouter=use_openrouter, vision_model=vision_model)
        vision_fallback = effective_id != requested_id

    effective_resolved = resolve_model_id(
        effective_id, use_openrouter=use_openrouter, default=default_model
    )
    effective_label = _model_label(
        effective_id, use_openrouter=use_openrouter, default=default_model
    )

    return ExtractionModelChoice(
        requested_id=requested_id,
        effective_id=effective_id,
        resolved_slug=effective_resolved,
        label=effective_label,
        requested_label=requested_label,
        vision_fallback=vision_fallback,
        needs_vision=needs_vision,
    )


def completion_model_fallback_chain(
    primary_model: str,
    *,
    use_openrouter: bool,
    default_model: str,
    vision_model: str | None = None,
) -> list[str]:
    """Ordered OpenRouter/API model slugs to try when extraction fails retriably.

    Chain: primary → default_model → vision_model → COMPLETION_FALLBACK_MODEL_IDS
    (deduplicated). Consumed by ``completion/extraction.py`` for tool-loop restarts
    and structured-output retries without re-running tools when possible.
    """
    seen: set[str] = set()
    chain: list[str] = []

    def add(raw: str | None) -> None:
        if not raw:
            return
        slug = resolve_model_id(raw, use_openrouter=use_openrouter, default=default_model)
        if slug in seen:
            return
        seen.add(slug)
        chain.append(slug)

    add(primary_model)
    add(default_model)
    add(vision_model)
    for model_id in COMPLETION_FALLBACK_MODEL_IDS:
        add(model_id)
    return chain
