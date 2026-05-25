"""Environment configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from extractor.models import (
    DEFAULT_MODEL_ID,
    DEFAULT_OPENROUTER_MODEL_ID,
    VISION_FALLBACK_MODEL_ID,
    resolve_model_id,
)
from extractor.types import ExtractionBackend

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api"

DEFAULT_EXTRACTOR_MODEL = DEFAULT_MODEL_ID
DEFAULT_SCHEMA_MODEL = DEFAULT_MODEL_ID
DEFAULT_OPENROUTER_EXTRACTOR_MODEL = DEFAULT_OPENROUTER_MODEL_ID
DEFAULT_OPENROUTER_SCHEMA_MODEL = DEFAULT_OPENROUTER_MODEL_ID
DEFAULT_MAX_PAGES = 50
DEFAULT_MAX_FILE_MB = 25
DEFAULT_REQUEST_TIMEOUT_S = 300
DEFAULT_UPLOAD_TTL_HOURS = 24
DEFAULT_VERIFY_TEXT_LAYER = False
DEFAULT_MAX_OUTPUT_TOKENS = 8000
DEFAULT_RATE_LIMIT_ENABLED = False
DEFAULT_RATE_LIMIT_PER_IP = 5
DEFAULT_RATE_LIMIT_PER_IP_WINDOW_SECONDS = 3600
DEFAULT_RATE_LIMIT_GLOBAL_DAILY = 20


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def resolve_app_root() -> Path:
    """Return directory containing ``ui/`` and ``storage/`` (repo root locally, ``/app`` in Docker)."""
    explicit = _env_str("EXTRACTOR_APP_ROOT")
    if explicit:
        return Path(explicit).resolve()
    dev_root = Path(__file__).resolve().parents[2]
    if (dev_root / "ui").is_dir():
        return dev_root
    docker_root = Path("/app")
    if (docker_root / "ui").is_dir():
        return docker_root
    return dev_root


PACKAGE_ROOT = resolve_app_root()
STORAGE_ROOT = PACKAGE_ROOT / "storage"
UPLOADS_ROOT = STORAGE_ROOT / "uploads"


def parse_extraction_backend(raw: str | None) -> ExtractionBackend:
    if raw and raw.strip().lower() in ("api", "completion", "openrouter"):
        return "api"
    return "agent"


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    openrouter_api_key: str | None
    anthropic_base_url: str | None
    extractor_model: str
    schema_model: str
    max_pages: int
    max_file_mb: int
    request_timeout_s: int
    verify_text_layer: bool
    max_output_tokens: int
    uploads_root: Path
    extraction_backend: ExtractionBackend
    vision_model: str
    rate_limit_enabled: bool
    rate_limit_per_ip: int
    rate_limit_per_ip_window_seconds: int
    rate_limit_global_daily: int

    @property
    def api_backend_available(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def use_openrouter(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def llm_configured(self) -> bool:
        return self.use_openrouter or bool(self.anthropic_api_key)

    @property
    def llm_provider(self) -> str | None:
        if self.use_openrouter:
            return "openrouter"
        if self.anthropic_api_key:
            return "anthropic"
        return None

    def resolve_model(self, model_id: str | None, *, default: str) -> str:
        return resolve_model_id(
            model_id,
            use_openrouter=self.use_openrouter,
            default=default,
        )

    def agent_sdk_env(self, *, model_slug: str | None = None) -> dict[str, str]:
        """Env vars passed to Claude Agent SDK subprocess (OpenRouter or direct Anthropic)."""
        env = dict(os.environ)
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(self.max_output_tokens)
        if self.use_openrouter:
            env["ANTHROPIC_BASE_URL"] = self.anthropic_base_url or OPENROUTER_BASE_URL
            env["ANTHROPIC_AUTH_TOKEN"] = self.openrouter_api_key or ""
            env["ANTHROPIC_API_KEY"] = ""
            if model_slug and not model_slug.startswith("anthropic/"):
                for key in (
                    "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                    "ANTHROPIC_DEFAULT_OPUS_MODEL",
                ):
                    env[key] = model_slug
            return env
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        return env

    @classmethod
    def from_env(cls) -> Settings:
        openrouter_api_key = _env_str("OPENROUTER_API_KEY") or _env_str("ANTHROPIC_AUTH_TOKEN")
        anthropic_base_url = _env_str("ANTHROPIC_BASE_URL")
        if openrouter_api_key and not anthropic_base_url:
            anthropic_base_url = OPENROUTER_BASE_URL

        use_openrouter = bool(openrouter_api_key)
        default_extractor = (
            DEFAULT_OPENROUTER_EXTRACTOR_MODEL if use_openrouter else DEFAULT_EXTRACTOR_MODEL
        )
        default_schema = (
            DEFAULT_OPENROUTER_SCHEMA_MODEL if use_openrouter else DEFAULT_SCHEMA_MODEL
        )

        return cls(
            anthropic_api_key=_env_str("ANTHROPIC_API_KEY"),
            openrouter_api_key=openrouter_api_key,
            anthropic_base_url=anthropic_base_url,
            extractor_model=os.environ.get("EXTRACTOR_MODEL", default_extractor),
            schema_model=os.environ.get("EXTRACTOR_SCHEMA_MODEL", default_schema),
            max_pages=int(os.environ.get("EXTRACTOR_MAX_PAGES", DEFAULT_MAX_PAGES)),
            max_file_mb=int(os.environ.get("EXTRACTOR_MAX_FILE_MB", DEFAULT_MAX_FILE_MB)),
            request_timeout_s=int(
                os.environ.get("EXTRACTOR_REQUEST_TIMEOUT_S", DEFAULT_REQUEST_TIMEOUT_S)
            ),
            verify_text_layer=env_bool(
                "EXTRACTOR_VERIFY_TEXT_LAYER", DEFAULT_VERIFY_TEXT_LAYER
            ),
            max_output_tokens=int(
                os.environ.get("EXTRACTOR_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS)
            ),
            uploads_root=UPLOADS_ROOT,
            extraction_backend=parse_extraction_backend(_env_str("EXTRACTOR_BACKEND") or "api"),
            vision_model=os.environ.get("EXTRACTOR_VISION_MODEL", VISION_FALLBACK_MODEL_ID),
            rate_limit_enabled=env_bool(
                "EXTRACTOR_RATE_LIMIT_ENABLED", DEFAULT_RATE_LIMIT_ENABLED
            ),
            rate_limit_per_ip=int(
                os.environ.get("EXTRACTOR_RATE_LIMIT_PER_IP", DEFAULT_RATE_LIMIT_PER_IP)
            ),
            rate_limit_per_ip_window_seconds=int(
                os.environ.get(
                    "EXTRACTOR_RATE_LIMIT_PER_IP_WINDOW_SECONDS",
                    DEFAULT_RATE_LIMIT_PER_IP_WINDOW_SECONDS,
                )
            ),
            rate_limit_global_daily=int(
                os.environ.get(
                    "EXTRACTOR_RATE_LIMIT_GLOBAL_DAILY", DEFAULT_RATE_LIMIT_GLOBAL_DAILY
                )
            ),
        )

    def ensure_dirs(self) -> None:
        self.uploads_root.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_dirs()
    return settings


def resolve_extraction_backend(
    options_backend: ExtractionBackend | None,
    settings: Settings,
) -> ExtractionBackend:
    if options_backend is not None:
        return options_backend
    return settings.extraction_backend
