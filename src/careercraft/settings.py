"""Runtime configuration.

Everything is overridable through ``CAREERCRAFT_*`` environment variables,
which is how MCP hosts configure a server (they hand it an ``env`` block in
their JSON config and nothing else). A few widely-recognised names such as
``OLLAMA_BASE_URL`` are accepted as aliases so an existing local setup keeps
working.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Annotated, Literal

from platformdirs import user_data_path
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from careercraft.errors import ValidationFailed
from careercraft.logging import get_logger

log = get_logger(__name__)


def _default_data_dir() -> Path:
    return user_data_path(appname="careercraft", appauthor=False)


class Settings(BaseSettings):
    """Process-wide configuration, read once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="CAREERCRAFT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- storage -----------------------------------------------------------
    data_dir: Path = Field(default_factory=_default_data_dir)
    """Where the SQLite database and uploaded resumes live."""

    max_upload_bytes: int = 10 * 1024 * 1024

    # NoDecode keeps pydantic-settings from JSON-decoding the raw env value
    # before the validators run. Without it a plain "C:\a,C:\b" raises a
    # SettingsError deep inside the source layer, and the CSV validator below
    # never gets a chance.
    allowed_paths: Annotated[list[Path], NoDecode] = Field(default_factory=lambda: [Path.home()])
    """Roots under which ``parse_resume(path=...)`` may read. Paths outside
    these roots are refused even in stdio mode."""

    # -- language model ----------------------------------------------------
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("CAREERCRAFT_OLLAMA_BASE_URL", "OLLAMA_BASE_URL"),
    )
    """Loopback IPv4 rather than ``localhost``: on hosts that resolve
    localhost to ``::1`` first, the name can reach a different daemon than
    the Ollama CLI does."""

    ollama_model: str = Field(
        default="llama3.2:1b",
        validation_alias=AliasChoices("CAREERCRAFT_OLLAMA_MODEL", "OLLAMA_MODEL"),
    )
    ollama_timeout: float = 180.0

    # -- parsing / matching ------------------------------------------------
    spacy_model: str = Field(
        default="en_core_web_sm",
        validation_alias=AliasChoices("CAREERCRAFT_SPACY_MODEL", "SPACY_MODEL_NAME"),
    )
    embedding_model: str = "all-MiniLM-L6-v2"
    skill_vocab_path: Path | None = None
    enable_ocr: bool = True
    """OCR is only attempted when a PDF yields almost no text, and only if the
    [ocr] extra is installed."""

    # -- job sources -------------------------------------------------------
    jobicy_base_url: str = "https://jobicy.com/api/v2/remote-jobs"
    job_fetch_timeout: float = 20.0
    job_cache_ttl_seconds: int = 3600

    retention_days: int = 30
    """How long a fetched posting stays in the store.

    Nothing was ever deleted: every search wrote up to fifty postings and the
    file only grew, holding descriptions the user saw once months ago. Pruning
    runs at startup and touches board data only — resumes, letters and saved
    jobs are the user's own and are kept regardless of age. Set to 0 to keep
    everything."""

    # -- transport ---------------------------------------------------------
    transport: Literal["stdio", "http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    http_path: str = "/mcp"
    auth_token: str | None = None
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    allow_unauthenticated_bind: bool = False
    """Permit a non-loopback bind with no auth token.

    A container has to bind ``0.0.0.0`` to receive forwarded traffic at all,
    and inside one that is not the same risk as doing it on a laptop: the
    exposure is whatever the operator published. So the guard stays on by
    default and this is the deliberate, named way past it — rather than
    softening the check itself, which would remove the protection everywhere
    to solve it in one place."""

    log_level: str = "INFO"

    @field_validator("allowed_paths", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept ``A,B,C`` as well as JSON lists — env vars are flat strings
        and requiring JSON here is a paper cut nobody needs."""
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass  # fall through and treat it as a plain CSV string
        return [part.strip() for part in text.split(",") if part.strip()]

    @field_validator("allowed_paths")
    @classmethod
    def _expand(cls, value: list[Path]) -> list[Path]:
        return [Path(p).expanduser() for p in value]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "careercraft.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    def ensure_dirs(self) -> None:
        """Create the data directories. Called once at startup, not on import."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def check_bind_safety(self) -> None:
        """Refuse to expose an unauthenticated server on a routable interface.

        A CareerCraft instance can read resumes off disk, so binding it to
        0.0.0.0 without a token is a data-exfiltration hole, not a
        convenience.
        """
        loopback = {"127.0.0.1", "::1", "localhost"}
        exposed = self.transport == "http" and self.host not in loopback
        if exposed and not self.auth_token and not self.allow_unauthenticated_bind:
            raise ValidationFailed(
                f"Refusing to bind {self.host}:{self.port} without an auth token.",
                remedy=(
                    "Set CAREERCRAFT_AUTH_TOKEN, bind 127.0.0.1 instead, or set "
                    "CAREERCRAFT_ALLOW_UNAUTHENTICATED_BIND=1 if the port is only "
                    "reachable from inside a container network."
                ),
            )
        if exposed and self.allow_unauthenticated_bind and not self.auth_token:
            log.warning(
                "bind.unauthenticated",
                host=self.host,
                port=self.port,
                detail="Anyone who can reach this port can read every stored resume.",
            )
        if "*" in self.cors_origins and self.auth_token:
            raise ValidationFailed(
                "CAREERCRAFT_CORS_ORIGINS='*' cannot be combined with an auth token.",
                remedy="List the exact origins that may call this server.",
            )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor. Tests clear it with ``get_settings.cache_clear()``."""
    return Settings()
