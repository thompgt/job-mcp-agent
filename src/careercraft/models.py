"""Domain models.

These are the tool return types, so their field names are part of the public
MCP contract: FastMCP derives each tool's ``outputSchema`` from them, and the
host model reads the field names as documentation. Prefer clarity over
brevity here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Tone = Literal["professional", "enthusiastic", "concise", "academic"]
Length = Literal["short", "medium", "long"]
Strategy = Literal["auto", "embedding", "keyword"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --------------------------------------------------------------------- jobs


class Job(Base):
    """A single job posting, normalised across sources."""

    id: str = Field(description="Stable content hash; the same posting always gets the same id.")
    title: str
    company: str = ""
    location: str = "Remote"
    description: str = ""
    url: str = ""
    source: str = ""
    level: str = ""
    job_type: str = ""
    salary: str = ""
    published_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=_utcnow)

    @staticmethod
    def make_id(title: str, company: str, url: str) -> str:
        """Content-address a posting so refetching does not duplicate it.

        v1 hashed the entire raw payload, which meant an upstream tweak to any
        field — a view counter, a reformatted description — minted a new id and
        the same job reappeared. Hashing only the identity triple is stable.
        """
        raw = f"{title.strip().lower()}|{company.strip().lower()}|{url.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_search_text(self) -> str:
        """Flatten into the text used for matching."""
        fields = [
            ("Title", self.title),
            ("Company", self.company),
            ("Level", self.level),
            ("Type", self.job_type),
            ("Location", self.location),
            ("Description", self.description),
        ]
        return "\n".join(f"{k}: {v}" for k, v in fields if v)


class JobSearchResult(Base):
    jobs: list[Job]
    total: int
    query: str = ""
    location: str = ""
    from_cache: bool = False
    source: str = ""


# ------------------------------------------------------------------ resumes


class Contacts(Base):
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    github: str | None = None


class EducationEntry(Base):
    text: str
    degree: str | None = None
    years: list[str] = Field(default_factory=list)


class ExperienceEntry(Base):
    organization: str = ""
    title: str = ""
    period: str | None = None
    highlights: list[str] = Field(default_factory=list)


class ProjectEntry(Base):
    name: str = ""
    role: str | None = None
    location: str | None = None
    period: str | None = None
    highlights: list[str] = Field(default_factory=list)


class ParsedResume(Base):
    """The output of resume parsing, and the input to matching."""

    id: str = ""
    name: str | None = None
    contacts: Contacts = Field(default_factory=Contacts)
    skills: list[str] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    projects: list[ProjectEntry] = Field(default_factory=list)

    raw_length: int = 0
    sections_detected: list[str] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)
    backend: str = "regex"
    """Which parsing backend produced this: ``regex``, ``spacy``, or
    ``spacy+layout``. Useful when a result looks thin — a regex-only parse
    cannot find a name that is not on one of the first lines."""
    used_ocr: bool = False
    source_name: str | None = None
    parsed_at: datetime = Field(default_factory=_utcnow)

    def to_search_text(self) -> str:
        """Flatten into the text used for matching."""
        parts: list[str] = []
        if self.name:
            parts.append(f"Name: {self.name}")
        if self.skills:
            parts.append("Skills: " + ", ".join(sorted(self.skills)))

        snippets = []
        for role in self.experience:
            header_bits = [b for b in (role.title, role.organization) if b]
            header = " at ".join(header_bits)
            if role.period:
                header = f"{header} ({role.period})" if header else role.period
            body = " ".join(h.strip() for h in role.highlights[:2])
            snippet = ": ".join(s for s in (header, body) if s)
            if snippet:
                snippets.append(snippet)
        if snippets:
            parts.append("Experience: " + " | ".join(snippets))

        if self.education:
            parts.append("Education: " + " | ".join(e.text for e in self.education if e.text))

        proj = []
        for p in self.projects[:3]:
            if not p.name:
                continue
            proj.append(f"{p.name} - {p.highlights[0]}" if p.highlights else p.name)
        if proj:
            parts.append("Projects: " + " | ".join(proj))

        return "\n".join(parts)


class ResumeSummary(Base):
    """A row in ``list_resumes`` — enough to pick one, not the whole document."""

    id: str
    name: str | None = None
    source_name: str | None = None
    skills_count: int = 0
    experience_count: int = 0
    parsed_at: datetime


# ----------------------------------------------------------------- matching


class JobMatch(Base):
    job: Job
    score: float = Field(ge=0.0, le=1.0, description="0-1; comparable only within one strategy.")
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(
        default_factory=list,
        description="Skills the posting emphasises that the resume does not mention.",
    )
    rationale: str = ""


class MatchResult(Base):
    matches: list[JobMatch]
    strategy_used: Literal["embedding", "keyword"]
    candidate_is_junior: bool = False
    jobs_considered: int = 0
    jobs_filtered_out: int = 0
    notes: list[str] = Field(default_factory=list)


# ------------------------------------------------------------ cover letters


class LetterBrief(Base):
    """What to say, when no language model is available to say it.

    Returned instead of prose when Ollama is unreachable. The MCP host's own
    model is generally *better* at writing the letter than a local 1B model —
    it just needs the grounded material, which is what this is.
    """

    company: str
    role: str
    opening_hook: str
    themes: list[str]
    evidence: list[str]
    company_hooks: list[str]
    closing: str
    paragraph_plan: list[str]


class CoverLetter(Base):
    job_id: str
    resume_id: str | None = None
    tone: Tone = "professional"
    length: Length = "medium"
    text: str | None = None
    brief: LetterBrief | None = None
    generated_by: Literal["ollama", "template", "brief"] = "template"
    model: str | None = None
    word_count: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


# ------------------------------------------------------------- capabilities


class Capability(Base):
    name: str
    available: bool
    detail: str = ""
    enable_with: str | None = None


class Capabilities(Base):
    """What this particular install can actually do.

    Exposed as the ``careercraft://capabilities`` resource so a host model can
    read it once and stop offering features that would only fail.
    """

    version: str
    python: str
    transport: str
    capabilities: list[Capability]
    default_match_strategy: Literal["embedding", "keyword"]

    def as_dict(self) -> dict[str, Any]:
        return {c.name: c.available for c in self.capabilities}
