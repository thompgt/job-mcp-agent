"""HTTP routes.

Every handler is a thin call into :class:`CareerCraftService`. Domain errors
are not caught here — the exception handlers in :mod:`careercraft.api.app` map
them onto status codes centrally, so a handler that forgets is impossible.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status

from careercraft import __version__
from careercraft.adapters.files import save_upload
from careercraft.api.deps import AuthDep, ServiceDep, SettingsDep
from careercraft.api.schemas import (
    HealthResponse,
    LetterRequest,
    LetterResponse,
    MatchRequest,
    ParseTextRequest,
    SavedJob,
    SaveJobRequest,
    SearchRequest,
)
from careercraft.capabilities import collect
from careercraft.models import (
    Capabilities,
    CoverLetter,
    Job,
    JobSearchResult,
    MatchResult,
    ParsedResume,
    ResumeSummary,
)

router = APIRouter()


# ------------------------------------------------------------------ meta


@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health(service: ServiceDep) -> HealthResponse:
    """Liveness, and enough about the install to be worth curling.

    A health check that only says "ok" tells you nothing you did not already
    know from the connection succeeding — but this is the one route without
    AuthDep, so what it says has to be safe to say to a stranger. It reports
    the install: version, and whether a model is reachable. It no longer
    reports the store's row counts, which described the user.
    """
    return HealthResponse(
        status="ok",
        version=__version__,
        llm_available=await service.llm_available(),
    )


@router.get("/capabilities", response_model=Capabilities, tags=["meta"])
async def capabilities(service: ServiceDep, settings: SettingsDep) -> Capabilities:
    """Which optional features this install has, and how to enable the rest."""
    ready, hint = await service.llm_status()
    return collect(transport="http", ollama_reachable=ready, ollama_hint=hint)


# ------------------------------------------------------------------ jobs


@router.post("/jobs/search", response_model=JobSearchResult, tags=["jobs"])
async def search_jobs(body: SearchRequest, service: ServiceDep, _: AuthDep) -> JobSearchResult:
    return await service.search_jobs(
        query=body.query,
        location=body.location,
        limit=body.limit,
        remote_only=body.remote_only,
        refresh=body.refresh,
    )


@router.get("/jobs/recent", response_model=list[Job], tags=["jobs"])
async def recent_jobs(
    service: ServiceDep,
    _: AuthDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Job]:
    return await service.recent_jobs(limit)


@router.get("/jobs/saved", response_model=list[SavedJob], tags=["jobs"])
async def saved_jobs(service: ServiceDep, _: AuthDep) -> list[SavedJob]:
    return [SavedJob(job=job, note=note) for job, note in await service.list_saved_jobs()]


@router.get("/jobs/{job_id}", response_model=Job, tags=["jobs"])
async def get_job(job_id: str, service: ServiceDep, _: AuthDep) -> Job:
    return await service.get_job(job_id)


@router.post("/jobs/{job_id}/save", response_model=Job, tags=["jobs"])
async def save_job(job_id: str, body: SaveJobRequest, service: ServiceDep, _: AuthDep) -> Job:
    return await service.save_job(job_id, body.note)


@router.delete("/jobs/{job_id}/save", status_code=status.HTTP_204_NO_CONTENT, tags=["jobs"])
async def unsave_job(job_id: str, service: ServiceDep, _: AuthDep) -> None:
    await service.unsave_job(job_id)


# --------------------------------------------------------------- resumes


@router.post("/resumes/upload", response_model=ParsedResume, tags=["resumes"])
async def upload_resume(
    service: ServiceDep,
    settings: SettingsDep,
    _: AuthDep,
    file: Annotated[UploadFile, File(description="A .pdf, .docx, .txt or .md resume.")],
) -> ParsedResume:
    """Accept an upload and parse it.

    The client-supplied filename is discarded rather than sanitised — only its
    extension survives — and the body is streamed to disk with the size cap
    enforced as bytes arrive, so an oversized upload cannot fill the disk
    before anyone checks.
    """
    settings.ensure_dirs()
    stored = await save_upload(
        _stream(file),
        filename=file.filename,
        upload_dir=settings.upload_dir,
        max_bytes=settings.max_upload_bytes,
    )
    try:
        return await service.parse_resume(path=stored, source_name=file.filename)
    finally:
        stored.unlink(missing_ok=True)


async def _stream(file: UploadFile, chunk: int = 64 * 1024) -> AsyncIterator[bytes]:
    while data := await file.read(chunk):
        yield data


@router.post("/resumes/parse", response_model=ParsedResume, tags=["resumes"])
async def parse_resume_text(
    body: ParseTextRequest, service: ServiceDep, _: AuthDep
) -> ParsedResume:
    """Parse pasted resume text.

    There is deliberately no ``path=`` equivalent here. Over HTTP the caller
    is not necessarily the person running the server, and a tool that reads
    server-side paths on request is a file-disclosure primitive.
    """
    return await service.parse_resume(
        text=body.text, source_name=body.source_name, persist=body.persist
    )


@router.get("/resumes", response_model=list[ResumeSummary], tags=["resumes"])
async def list_resumes(
    service: ServiceDep,
    _: AuthDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[ResumeSummary]:
    return await service.list_resumes(limit)


@router.get("/resumes/{resume_id}", response_model=ParsedResume, tags=["resumes"])
async def get_resume(resume_id: str, service: ServiceDep, _: AuthDep) -> ParsedResume:
    return await service.get_resume(resume_id)


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["resumes"])
async def delete_resume(resume_id: str, service: ServiceDep, _: AuthDep) -> None:
    await service.delete_resume(resume_id)


# -------------------------------------------------------------- matching


@router.post("/match", response_model=MatchResult, tags=["matching"])
async def match_jobs(body: MatchRequest, service: ServiceDep, _: AuthDep) -> MatchResult:
    return await service.match_jobs(
        resume_id=body.resume_id,
        query=body.query,
        location=body.location,
        top_k=body.top_k,
        min_score=body.min_score,
        strategy=body.strategy,
        filter_seniority=body.filter_seniority,
    )


# --------------------------------------------------------------- letters


@router.post("/letters", response_model=LetterResponse, tags=["letters"])
async def generate_letter(body: LetterRequest, service: ServiceDep, _: AuthDep) -> LetterResponse:
    letter_id, letter = await service.generate_cover_letter(
        job_id=body.job_id,
        resume_id=body.resume_id,
        tone=body.tone,
        length=body.length,
        model=body.model,
        allow_brief=body.allow_brief,
    )
    return LetterResponse(id=letter_id, letter=letter)


@router.get("/letters/{letter_id}", response_model=CoverLetter, tags=["letters"])
async def get_letter(letter_id: str, service: ServiceDep, _: AuthDep) -> CoverLetter:
    return await service.get_letter(letter_id)
