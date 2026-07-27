"""The application service.

One object that owns the store, the job provider and the language model, and
implements every operation the product offers. Both the MCP server and the
HTTP API are thin shells over this — which is the whole point of the
consolidation: v1 had the pipeline implemented twice, once in
``mcp_pipeline_server.py`` and again in ``server/api_frontend.py``, and the two
copies had already drifted.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import uuid4

import anyio
import anyio.to_thread

from careercraft.adapters.llm import NullProvider, OllamaProvider
from careercraft.adapters.storage import SqliteStore
from careercraft.core.jobs import JobicyProvider, JobProvider, JobQuery, MockProvider
from careercraft.core.letters import generate_letter
from careercraft.core.matching import rank_jobs
from careercraft.core.resume import extract_text, parse_resume_text
from careercraft.core.resume.extract import LayoutLine
from careercraft.core.resume.skills import load_extra_terms
from careercraft.errors import NotFound, ValidationFailed
from careercraft.llm import LLMProvider
from careercraft.logging import get_logger
from careercraft.models import (
    CoverLetter,
    Job,
    JobSearchResult,
    Length,
    MatchResult,
    ParsedResume,
    ResumeSummary,
    Strategy,
    Tone,
)
from careercraft.settings import Settings, get_settings

log = get_logger(__name__)

#: Embedding and spaCy work is CPU-bound and torch is not reentrant, so all of
#: it funnels through one worker slot. Without this, two concurrent match calls
#: on a full install can wedge the process.
_CPU_LIMITER = anyio.CapacityLimiter(1)

ProgressFn = Callable[[str, float], Awaitable[None]]


async def _noop_progress(message: str, fraction: float) -> None:
    return None


class CareerCraftService:
    """Everything the product does, with no transport in sight."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: SqliteStore | None = None,
        job_provider: JobProvider | None = None,
        llm: LLMProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or SqliteStore(self.settings.db_path)
        self.jobs: JobProvider = job_provider or JobicyProvider(
            base_url=self.settings.jobicy_base_url,
            timeout=self.settings.job_fetch_timeout,
        )
        self.mock_jobs = MockProvider()
        self.llm: LLMProvider = llm or OllamaProvider(
            base_url=self.settings.ollama_base_url,
            model=self.settings.ollama_model,
            timeout=self.settings.ollama_timeout,
        )
        self._extra_skills = load_extra_terms(self.settings.skill_vocab_path)

    async def startup(self) -> None:
        self.settings.ensure_dirs()
        await self.store.initialize()

    async def shutdown(self) -> None:
        """Release the providers' connection pools.

        Both HTTP providers keep one client alive for their lifetime rather
        than building a fresh one per call — constructing an ``AsyncClient``
        loads a TLS trust store, which is close to a second on Windows. That
        makes closing them our job.
        """
        for provider in (self.jobs, self.llm):
            closer = getattr(provider, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    log.debug("shutdown.close_failed", provider=getattr(provider, "name", "?"))

    # ---------------------------------------------------------------- jobs

    @staticmethod
    def _cache_key(query: JobQuery, source: str) -> str:
        raw = f"{source}|{query.query}|{query.location}|{query.limit}|{query.remote_only}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def search_jobs(
        self,
        *,
        query: str = "",
        location: str = "",
        limit: int = 25,
        remote_only: bool = True,
        refresh: bool = False,
        source: str = "jobicy",
        progress: ProgressFn = _noop_progress,
    ) -> JobSearchResult:
        """Fetch postings, caching by query so repeat calls are instant."""
        if limit < 1:
            raise ValidationFailed("limit must be at least 1.", remedy="Try limit=25.")

        job_query = JobQuery(
            query=query.strip(), location=location.strip(), limit=limit, remote_only=remote_only
        )
        provider = self.mock_jobs if source == "mock" else self.jobs
        key = self._cache_key(job_query, provider.name)

        if not refresh:
            cached = await self.store.cached_search(key, self.settings.job_cache_ttl_seconds)
            if cached:
                await progress("Using cached results", 1.0)
                return JobSearchResult(
                    jobs=cached[:limit],
                    total=len(cached[:limit]),
                    query=query,
                    location=location,
                    from_cache=True,
                    source=provider.name,
                )

        await progress(f"Searching {provider.name}", 0.2)
        jobs = await provider.search(job_query)

        await progress(f"Storing {len(jobs)} postings", 0.8)
        await self.store.upsert_jobs(jobs)
        await self.store.cache_search(key, jobs)
        await progress("Done", 1.0)

        return JobSearchResult(
            jobs=jobs[:limit],
            total=len(jobs[:limit]),
            query=query,
            location=location,
            from_cache=False,
            source=provider.name,
        )

    async def get_job(self, job_id: str) -> Job:
        job = await self.store.get_job(job_id)
        if job is None:
            raise NotFound(
                "job",
                job_id,
                remedy="Run search_jobs first, or check the id against careercraft://jobs/recent.",
            )
        return job

    async def recent_jobs(self, limit: int = 50) -> list[Job]:
        return await self.store.recent_jobs(limit)

    async def save_job(self, job_id: str, note: str = "") -> Job:
        job = await self.get_job(job_id)
        await self.store.save_job(job_id, note)
        return job

    async def list_saved_jobs(self) -> list[tuple[Job, str]]:
        return await self.store.list_saved_jobs()

    async def unsave_job(self, job_id: str) -> bool:
        return await self.store.unsave_job(job_id)

    # ------------------------------------------------------------- resumes

    def _parse_sync(
        self,
        text: str,
        *,
        layout_lines: list[LayoutLine] | None,
        source_name: str | None,
        used_ocr: bool,
    ) -> ParsedResume:
        return parse_resume_text(
            text,
            layout_lines=layout_lines,
            spacy_model=self.settings.spacy_model,
            extra_skill_terms=self._extra_skills,
            source_name=source_name,
            used_ocr=used_ocr,
        )

    async def parse_resume(
        self,
        *,
        path: Path | None = None,
        text: str | None = None,
        source_name: str | None = None,
        persist: bool = True,
        progress: ProgressFn = _noop_progress,
    ) -> ParsedResume:
        """Parse a resume from a file or from raw text.

        Extraction and parsing both run in a worker thread: PDF reading and
        spaCy are blocking, and holding the event loop through them stalls
        every other in-flight tool call.
        """
        if (path is None) == (text is None):
            raise ValidationFailed(
                "Provide exactly one of path or text.",
                remedy="Pass path= for a file on disk, or text= for pasted resume text.",
            )

        if path is not None:
            await progress(f"Reading {path.name}", 0.2)
            document = await anyio.to_thread.run_sync(
                lambda: extract_text(path, enable_ocr=self.settings.enable_ocr)
            )
            body, layout, name, used_ocr = (
                document.text,
                document.layout_lines,
                document.source_name,
                document.used_ocr,
            )
        else:
            body, layout, name, used_ocr = text or "", None, source_name, False

        if not body.strip():
            raise ValidationFailed(
                "The resume contains no readable text.",
                remedy=(
                    "If this is a scanned PDF, install the OCR extra: "
                    "pip install 'careercraft-mcp[ocr]'"
                ),
            )

        await progress("Parsing", 0.6)
        resume = await anyio.to_thread.run_sync(
            lambda: self._parse_sync(
                body, layout_lines=layout, source_name=name, used_ocr=used_ocr
            ),
            limiter=_CPU_LIMITER,
        )
        resume.id = uuid4().hex[:12]

        if persist:
            await self.store.save_resume(resume)
        await progress("Done", 1.0)
        log.info(
            "resume.parsed",
            resume_id=resume.id,
            skills=len(resume.skills),
            backend=resume.backend,
        )
        return resume

    async def get_resume(self, resume_id: str | None) -> ParsedResume:
        """Fetch a resume by id, or the most recent one when id is omitted."""
        resume = (
            await self.store.get_resume(resume_id)
            if resume_id
            else await self.store.latest_resume()
        )
        if resume is None:
            raise NotFound(
                "resume",
                resume_id or "(most recent)",
                remedy="Call parse_resume first, or list_resumes to see stored ones.",
            )
        return resume

    async def list_resumes(self, limit: int = 20) -> list[ResumeSummary]:
        return await self.store.list_resumes(limit)

    async def delete_resume(self, resume_id: str) -> bool:
        return await self.store.delete_resume(resume_id)

    # ------------------------------------------------------------ matching

    async def match_jobs(
        self,
        *,
        resume_id: str | None = None,
        resume: ParsedResume | None = None,
        query: str = "",
        location: str = "",
        top_k: int = 10,
        min_score: float = 0.25,
        strategy: Strategy = "auto",
        filter_seniority: bool = True,
        pool_size: int = 50,
        source: str = "jobicy",
        progress: ProgressFn = _noop_progress,
    ) -> MatchResult:
        """Rank postings against a resume, fetching a pool if needed."""
        if not 0.0 <= min_score <= 1.0:
            raise ValidationFailed(
                "min_score must be between 0 and 1.", remedy="The default is 0.25."
            )

        target = resume or await self.get_resume(resume_id)

        await progress("Gathering postings", 0.2)
        if query:
            search = await self.search_jobs(
                query=query, location=location, limit=pool_size, source=source
            )
            pool = search.jobs
        else:
            pool = await self.store.recent_jobs(pool_size)

        if not pool:
            raise NotFound(
                "job pool",
                query or "recent",
                remedy="Run search_jobs first, or pass query= to fetch postings now.",
            )

        await progress(f"Scoring {len(pool)} postings", 0.6)
        result = await anyio.to_thread.run_sync(
            lambda: rank_jobs(
                target,
                pool,
                top_k=top_k,
                min_score=min_score,
                strategy=strategy,
                filter_seniority=filter_seniority,
                embedding_model=self.settings.embedding_model,
            ),
            limiter=_CPU_LIMITER,
        )
        await progress("Done", 1.0)
        log.info(
            "jobs.matched",
            strategy=result.strategy_used,
            considered=result.jobs_considered,
            returned=len(result.matches),
        )
        return result

    # ------------------------------------------------------------- letters

    async def generate_cover_letter(
        self,
        *,
        job_id: str,
        resume_id: str | None = None,
        tone: Tone = "professional",
        length: Length = "medium",
        model: str | None = None,
        allow_brief: bool = True,
        persist: bool = True,
        progress: ProgressFn = _noop_progress,
    ) -> tuple[str, CoverLetter]:
        """Draft a letter. Returns ``(letter_id, letter)``."""
        job = await self.get_job(job_id)
        resume = await self.get_resume(resume_id)

        await progress("Drafting", 0.3)
        letter = await generate_letter(
            resume,
            job,
            provider=self.llm,
            tone=tone,
            length=length,
            model=model or self.settings.ollama_model,
            allow_brief=allow_brief,
        )
        letter.resume_id = resume.id or None

        letter_id = uuid4().hex[:12]
        if persist:
            await self.store.save_letter(letter_id, letter)
        await progress("Done", 1.0)
        log.info("letter.generated", letter_id=letter_id, via=letter.generated_by)
        return letter_id, letter

    async def get_letter(self, letter_id: str) -> CoverLetter:
        letter = await self.store.get_letter(letter_id)
        if letter is None:
            raise NotFound("cover letter", letter_id)
        return letter

    # -------------------------------------------------------------- admin

    async def llm_available(self) -> bool:
        return await self.llm.is_available()

    async def stats(self) -> dict[str, int]:
        return await self.store.stats()


def build_service(settings: Settings | None = None) -> CareerCraftService:
    """Construct the service, wiring in a null LLM when generation is off."""
    resolved = settings or get_settings()
    llm: LLMProvider
    if resolved.ollama_base_url.lower() in ("", "none", "disabled"):
        llm = NullProvider()
    else:
        llm = OllamaProvider(
            base_url=resolved.ollama_base_url,
            model=resolved.ollama_model,
            timeout=resolved.ollama_timeout,
        )
    return CareerCraftService(resolved, llm=llm)
