"""Request bodies for the HTTP API.

Responses reuse the domain models from :mod:`careercraft.models` verbatim, so
the OpenAPI schema the frontend generates its client from and the MCP tool
output schemas describe the same shapes. Only the inputs need declaring: over
HTTP they arrive as JSON bodies rather than as tool arguments.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from careercraft.core.matching import DEFAULT_MIN_SCORE
from careercraft.models import CoverLetter, Job, Length, Strategy, Tone


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRequest(Body):
    query: str = ""
    location: str = ""
    limit: int = Field(default=25, ge=1, le=50)
    remote_only: bool = True
    refresh: bool = False


class ParseTextRequest(Body):
    text: str = Field(min_length=1)
    source_name: str | None = None
    persist: bool = True


class MatchRequest(Body):
    resume_id: str | None = None
    query: str = ""
    location: str = ""
    top_k: int = Field(default=10, ge=1, le=50)
    min_score: float = Field(default=DEFAULT_MIN_SCORE, ge=0.0, le=1.0)
    strategy: Strategy = "auto"
    filter_seniority: bool = True


class LetterRequest(Body):
    job_id: str
    resume_id: str | None = None
    tone: Tone = "professional"
    length: Length = "medium"
    model: str | None = None
    allow_brief: bool = Field(
        default=False,
        description=(
            "The web UI has no model to hand a brief to, so it defaults to false and "
            "gets finished prose from the template instead."
        ),
    )


class SaveJobRequest(Body):
    note: str = ""


class LetterResponse(Body):
    """A generated letter plus the id it was stored under."""

    id: str
    letter: CoverLetter


class SavedJob(Body):
    job: Job
    note: str = ""


class ErrorResponse(Body):
    """The body of every 4xx and 5xx this API returns."""

    code: str = Field(description="Stable machine-readable error code.")
    message: str
    remedy: str | None = Field(
        default=None, description="What the caller can do about it, when there is an answer."
    )


class HealthResponse(Body):
    status: str
    version: str
    llm_available: bool
    stats: dict[str, int]
