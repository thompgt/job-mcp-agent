"""The MCP server.

This is the primary interface to CareerCraft: seven tools, six resources and
three prompts over :class:`~careercraft.service.CareerCraftService`.

Three rules hold everywhere in this module.

**stdout is sacred.** Under stdio transport stdout carries JSON-RPC frames, so
nothing here prints. Logging is configured to stderr in
:func:`careercraft.logging.configure_logging` and every diagnostic goes through
``ctx.info`` or the structlog logger.

**Errors are errors.** A failed tool raises :class:`ToolError` carrying the
``remedy`` verbatim. v1 returned ``{"status": "error", ...}`` with a 200, which
reads to the calling model as a successful call that happened to return an
error-shaped object, and it would cheerfully summarise the failure as a result.

**Local paths are a privilege of stdio.** ``parse_resume(path=...)`` goes
through :func:`careercraft.adapters.files.resolve_allowed`, which refuses
outright when the server is reachable over HTTP.
"""

# NOTE: deliberately no ``from __future__ import annotations`` here. FastMCP
# builds each tool's schema by resolving the handler's annotations through a
# wrapper function, and string annotations do not resolve against this module's
# globals in that path. Real annotation objects are required. ``X | None``
# works at runtime on every Python this package supports (3.10+).

import json
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from careercraft import __version__
from careercraft.adapters.files import resolve_allowed
from careercraft.capabilities import collect
from careercraft.errors import CareerCraftError
from careercraft.logging import get_logger
from careercraft.models import (
    Capabilities,
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
from careercraft.service import CareerCraftService, ProgressFn, build_service
from careercraft.settings import Settings, get_settings

log = get_logger(__name__)

INSTRUCTIONS = """\
CareerCraft turns a resume into targeted job applications, entirely on the \
user's machine.

The usual flow is: parse_resume -> match_jobs -> generate_cover_letter. \
match_jobs will fetch postings itself if you pass query=, so you rarely need \
search_jobs first.

Read careercraft://capabilities before offering anything: this install may \
lack PDF reading, semantic matching or a local language model, and each \
capability entry names the exact command that enables it.

When generate_cover_letter cannot reach Ollama it returns a `brief` instead of \
`text` — grounded themes, evidence drawn from the resume, and a paragraph \
plan. Write the letter yourself from that brief rather than reporting a \
failure; it is usually the better outcome.
"""


def _progress(ctx: Context | None) -> ProgressFn:
    """Adapt an MCP context into the service's progress callback."""
    if ctx is None:

        async def noop(message: str, fraction: float) -> None:
            return None

        return noop

    async def report(message: str, fraction: float) -> None:
        await ctx.report_progress(fraction, total=1.0, message=message)

    return report


def _fail(exc: CareerCraftError) -> ToolError:
    """Map a domain error onto the protocol, keeping the remedy attached."""
    detail = f"{exc.message} {exc.remedy}".strip() if exc.remedy else exc.message
    return ToolError(f"[{exc.code}] {detail}")


def build_server(settings: Settings | None = None, *, service: CareerCraftService | None = None) -> FastMCP:
    """Construct the server.

    ``service`` is injectable so tests can drive the whole tool surface against
    a temp-directory store and a mock job provider through FastMCP's in-memory
    client transport — no subprocess, no network.
    """
    resolved = settings or get_settings()
    svc = service or build_service(resolved)

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[None]:
        await svc.startup()
        log.info("server.ready", version=__version__, transport=resolved.transport)
        yield

    mcp: FastMCP = FastMCP(
        name="careercraft",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/thomaspequegnot/careercraft-mcp",
        lifespan=lifespan,
    )

    # ------------------------------------------------------------- tools

    @mcp.tool
    async def search_jobs(
        query: Annotated[str, Field(description="Role keywords, e.g. 'data analyst'.")] = "",
        location: Annotated[str, Field(description="Region filter, e.g. 'USA'.")] = "",
        limit: Annotated[int, Field(ge=1, le=50, description="Maximum postings.")] = 25,
        remote_only: bool = True,
        refresh: Annotated[bool, Field(description="Bypass the cache.")] = False,
        ctx: Context | None = None,
    ) -> JobSearchResult:
        """Fetch job postings from the remote board.

        Results are cached, so repeat calls for the same query are instant.
        Pass refresh=True to force a live fetch.
        """
        try:
            return await svc.search_jobs(
                query=query,
                location=location,
                limit=limit,
                remote_only=remote_only,
                refresh=refresh,
                progress=_progress(ctx),
            )
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    @mcp.tool
    async def get_job(job_id: str) -> Job:
        """Retrieve one stored posting in full, including its description."""
        try:
            return await svc.get_job(job_id)
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    @mcp.tool
    async def parse_resume(
        path: Annotated[
            str | None,
            Field(
                description=(
                    "Absolute path to a .pdf, .docx, .txt or .md resume. "
                    "Rejected when this server is reached over HTTP."
                )
            ),
        ] = None,
        text: Annotated[str | None, Field(description="Raw resume text instead of a file.")] = None,
        persist: bool = True,
        ctx: Context | None = None,
    ) -> ParsedResume:
        """Extract skills, experience, education and contacts from a resume.

        Provide exactly one of path or text. The returned `id` is what
        match_jobs and generate_cover_letter take.
        """
        try:
            resolved_path = (
                resolve_allowed(path, resolved.allowed_paths, transport=resolved.transport)
                if path
                else None
            )
            return await svc.parse_resume(
                path=resolved_path,
                text=text,
                persist=persist,
                progress=_progress(ctx),
            )
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    @mcp.tool
    async def list_resumes(
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> list[ResumeSummary]:
        """List stored resumes, newest first."""
        return await svc.list_resumes(limit)

    @mcp.tool
    async def match_jobs(
        resume_id: Annotated[
            str | None, Field(description="Omit to use the most recently parsed resume.")
        ] = None,
        query: Annotated[
            str, Field(description="Fetch a fresh pool for these keywords before ranking.")
        ] = "",
        location: str = "",
        top_k: Annotated[int, Field(ge=1, le=50)] = 10,
        min_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.25,
        strategy: Annotated[
            Strategy, Field(description="'auto' picks embeddings when installed, else keyword.")
        ] = "auto",
        filter_seniority: Annotated[
            bool,
            Field(description="Drop postings whose seniority or degree the candidate cannot meet."),
        ] = True,
        ctx: Context | None = None,
    ) -> MatchResult:
        """Rank job postings against a resume, with per-job rationales.

        Each match reports which of the candidate's skills the posting asks for
        and which it asks for that the resume does not mention — the second
        list is the useful one for tailoring an application.
        """
        try:
            return await svc.match_jobs(
                resume_id=resume_id,
                query=query,
                location=location,
                top_k=top_k,
                min_score=min_score,
                strategy=strategy,
                filter_seniority=filter_seniority,
                progress=_progress(ctx),
            )
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    @mcp.tool
    async def generate_cover_letter(
        job_id: str,
        resume_id: Annotated[
            str | None, Field(description="Omit to use the most recently parsed resume.")
        ] = None,
        tone: Tone = "professional",
        length: Length = "medium",
        model: Annotated[
            str | None, Field(description="Override the Ollama model, e.g. 'llama3.2:3b'.")
        ] = None,
        allow_brief: Annotated[
            bool,
            Field(
                description=(
                    "When no local model is reachable, return a grounded brief for you to "
                    "write from instead of failing."
                )
            ),
        ] = True,
        ctx: Context | None = None,
    ) -> CoverLetter:
        """Draft a cover letter grounded in the resume and the posting.

        If `text` is null and `brief` is set, no local model was reachable —
        write the letter yourself from the brief. Do not invent skills the
        resume does not evidence.
        """
        try:
            letter_id, letter = await svc.generate_cover_letter(
                job_id=job_id,
                resume_id=resume_id,
                tone=tone,
                length=length,
                model=model,
                allow_brief=allow_brief,
                progress=_progress(ctx),
            )
        except CareerCraftError as exc:
            raise _fail(exc) from exc

        if ctx is not None:
            await ctx.info(f"Saved as careercraft://letters/{letter_id}")
        return letter

    @mcp.tool
    async def save_job(
        job_id: str,
        note: Annotated[str, Field(description="Why this one is worth keeping.")] = "",
    ) -> Job:
        """Bookmark a posting so it survives cache expiry."""
        try:
            return await svc.save_job(job_id, note)
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    # --------------------------------------------------------- resources

    @mcp.resource(
        "careercraft://capabilities",
        name="capabilities",
        description="Which features this install supports, and how to enable the rest.",
        mime_type="application/json",
    )
    async def capabilities_resource() -> Capabilities:
        return collect(
            transport=resolved.transport,
            ollama_reachable=await svc.llm_available(),
        )

    @mcp.resource(
        "careercraft://resumes",
        name="resumes",
        description="Stored resumes, newest first.",
        mime_type="application/json",
    )
    async def resumes_resource() -> list[ResumeSummary]:
        return await svc.list_resumes(50)

    @mcp.resource(
        "careercraft://resume/{resume_id}",
        name="resume",
        description="One parsed resume in full.",
        mime_type="application/json",
    )
    async def resume_resource(resume_id: str) -> ParsedResume:
        try:
            return await svc.get_resume(resume_id)
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    @mcp.resource(
        "careercraft://jobs/recent",
        name="recent_jobs",
        description="Postings fetched recently, newest first.",
        mime_type="application/json",
    )
    async def recent_jobs_resource() -> list[Job]:
        return await svc.recent_jobs(50)

    @mcp.resource(
        "careercraft://job/{job_id}",
        name="job",
        description="One stored posting in full.",
        mime_type="application/json",
    )
    async def job_resource(job_id: str) -> Job:
        try:
            return await svc.get_job(job_id)
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    @mcp.resource(
        "careercraft://letters/{letter_id}",
        name="letter",
        description="A generated cover letter.",
        mime_type="application/json",
    )
    async def letter_resource(letter_id: str) -> CoverLetter:
        try:
            return await svc.get_letter(letter_id)
        except CareerCraftError as exc:
            raise _fail(exc) from exc

    @mcp.resource(
        "careercraft://saved",
        name="saved_jobs",
        description="Bookmarked postings with their notes.",
        mime_type="application/json",
    )
    async def saved_jobs_resource() -> str:
        saved = await svc.list_saved_jobs()
        return json.dumps(
            [{"job": job.model_dump(mode="json"), "note": note} for job, note in saved],
            indent=2,
        )

    # ----------------------------------------------------------- prompts

    @mcp.prompt(name="job_search_workflow")
    def job_search_workflow(
        resume_path: str = "",
        role: str = "",
        location: str = "",
    ) -> str:
        """End-to-end: parse a resume, find matching roles, explain the shortlist."""
        source = f"the resume at {resume_path}" if resume_path else "my most recently parsed resume"
        target = role or "roles that fit my background"
        where = f" in {location}" if location else ""
        return (
            f"Using CareerCraft, work through this in order:\n\n"
            f"1. Read careercraft://capabilities so you know what this install supports.\n"
            f"2. Parse {source} and tell me what it found — skills, and anything it "
            f"flagged in parse_warnings.\n"
            f"3. Run match_jobs with query='{target}'{where}.\n"
            f"4. For the top matches, explain in plain language why each one scored where "
            f"it did, leaning on matched_skills and missing_skills rather than the number.\n"
            f"5. Tell me which single posting is the strongest fit and what I would need to "
            f"address to be competitive for it.\n\n"
            f"Do not claim I have any skill that is not in the parsed resume."
        )

    @mcp.prompt(name="tailor_cover_letter")
    def tailor_cover_letter(
        job_id: str,
        resume_id: str = "",
        tone: str = "professional",
    ) -> str:
        """Draft a cover letter for one posting, grounded in the resume."""
        which = f" with resume_id='{resume_id}'" if resume_id else ""
        return (
            f"Call generate_cover_letter for job_id='{job_id}'{which} with tone='{tone}'.\n\n"
            f"If it returns `text`, review it against the posting and tighten anything vague "
            f"or generic before showing it to me.\n\n"
            f"If it returns `brief` instead of `text`, no local model was reachable — write "
            f"the letter yourself from the brief. Follow the paragraph_plan, use only the "
            f"listed evidence, and work in the company_hooks naturally.\n\n"
            f"Either way: no invented experience, no skills the resume does not evidence, and "
            f"no phrase resembling 'I am writing to express my interest'."
        )

    @mcp.prompt(name="resume_feedback")
    def resume_feedback(resume_id: str = "", target_role: str = "") -> str:
        """Critique a parsed resume against a target role."""
        which = f"careercraft://resume/{resume_id}" if resume_id else "my most recent resume"
        goal = target_role or "the roles I have been matching against"
        return (
            f"Read {which}, then match_jobs against '{goal}' to see what postings actually "
            f"ask for.\n\n"
            f"Give me:\n"
            f"- Skills that appear repeatedly in missing_skills across the matches, ranked by "
            f"how often they show up.\n"
            f"- Places where the parse came out thin — empty sections, low skill counts, "
            f"anything in parse_warnings — since a parser struggling is a signal a recruiter's "
            f"ATS will too.\n"
            f"- Three concrete edits, each naming the section and what to write.\n\n"
            f"Be direct. Do not pad this with encouragement."
        )

    return mcp


def build_default_server() -> FastMCP:
    """Entry point for ``fastmcp run`` and for the MCP Inspector."""
    return build_server()


__all__ = ["build_server", "build_default_server", "INSTRUCTIONS"]
