"""The application service, end to end against a temp store and mock jobs."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from careercraft.core.matching import DEFAULT_MIN_SCORE
from careercraft.errors import NotFound, ValidationFailed


async def test_parse_persists_and_assigns_an_id(service, resume_text):
    resume = await service.parse_resume(text=resume_text, source_name="cv.txt")
    assert resume.id
    assert resume.name == "Jane Doe"
    assert (await service.get_resume(resume.id)).id == resume.id


async def test_parse_from_a_file(service, tmp_path: Path, resume_text):
    path = tmp_path / "cv.txt"
    path.write_text(resume_text, encoding="utf-8")
    resume = await service.parse_resume(path=path)
    assert resume.skills
    assert resume.source_name == "cv.txt"


async def test_parse_requires_exactly_one_source(service, resume_text):
    with pytest.raises(ValidationFailed):
        await service.parse_resume()
    with pytest.raises(ValidationFailed):
        await service.parse_resume(path=Path("x"), text=resume_text)


async def test_parse_rejects_an_empty_document(service):
    with pytest.raises(ValidationFailed) as excinfo:
        await service.parse_resume(text="   \n  ")
    assert "ocr" in str(excinfo.value).lower()


async def test_progress_is_reported(service, resume_text):
    seen: list[tuple[str, float]] = []

    async def record(message: str, fraction: float) -> None:
        seen.append((message, fraction))

    await service.parse_resume(text=resume_text, progress=record)
    assert seen
    assert seen[-1][1] == 1.0
    assert all(0.0 <= f <= 1.0 for _, f in seen)


async def test_get_resume_without_an_id_returns_the_latest(service, resume_text):
    await service.parse_resume(text=resume_text)
    second = await service.parse_resume(text=resume_text)
    assert (await service.get_resume(None)).id == second.id


async def test_get_resume_on_an_empty_store_says_what_to_do(service):
    with pytest.raises(NotFound) as excinfo:
        await service.get_resume(None)
    assert "parse_resume" in str(excinfo.value)


async def test_search_caches_by_query(service):
    first = await service.search_jobs(query="data", limit=5)
    assert first.from_cache is False
    second = await service.search_jobs(query="data", limit=5)
    assert second.from_cache is True
    assert [j.id for j in first.jobs] == [j.id for j in second.jobs]


async def test_refresh_bypasses_the_cache(service):
    await service.search_jobs(query="data", limit=5)
    again = await service.search_jobs(query="data", limit=5, refresh=True)
    assert again.from_cache is False


async def test_a_different_query_is_a_different_cache_entry(service):
    await service.search_jobs(query="data", limit=5)
    other = await service.search_jobs(query="engineer", limit=5)
    assert other.from_cache is False


async def test_search_rejects_a_nonsense_limit(service):
    with pytest.raises(ValidationFailed):
        await service.search_jobs(query="data", limit=0)


async def test_get_job_names_the_recovery(service):
    with pytest.raises(NotFound) as excinfo:
        await service.get_job("nope")
    assert "search_jobs" in str(excinfo.value)


async def test_match_fetches_its_own_pool(service, resume_text):
    resume = await service.parse_resume(text=resume_text)
    result = await service.match_jobs(resume_id=resume.id, query="data", min_score=0.0)
    assert result.matches
    assert result.strategy_used == "keyword"
    assert all(m.rationale for m in result.matches)


async def test_match_uses_stored_jobs_when_no_query_is_given(service, resume_text):
    resume = await service.parse_resume(text=resume_text)
    await service.search_jobs(query="data", limit=10)
    result = await service.match_jobs(resume_id=resume.id, min_score=0.0)
    assert result.jobs_considered > 0


async def test_match_with_no_jobs_at_all_explains_itself(service, resume_text):
    resume = await service.parse_resume(text=resume_text)
    with pytest.raises(NotFound) as excinfo:
        await service.match_jobs(resume_id=resume.id)
    assert "search_jobs" in str(excinfo.value)


async def test_match_validates_min_score(service, resume_text):
    resume = await service.parse_resume(text=resume_text)
    with pytest.raises(ValidationFailed):
        await service.match_jobs(resume_id=resume.id, min_score=7.0)


async def test_the_min_score_remedy_names_the_real_default(service, resume_text):
    """The remedy said 0.25 long after the default became 0.15.

    A remedy that names the wrong number is worse than none: it tells the user
    to set a threshold that silently changes their results.
    """
    resume = await service.parse_resume(text=resume_text)
    with pytest.raises(ValidationFailed) as excinfo:
        await service.match_jobs(resume_id=resume.id, min_score=7.0)

    assert str(DEFAULT_MIN_SCORE) in str(excinfo.value)
    assert inspect.signature(service.match_jobs).parameters["min_score"].default == (
        DEFAULT_MIN_SCORE
    )


async def test_cover_letter_falls_back_to_a_brief_without_ollama(service, resume_text):
    resume = await service.parse_resume(text=resume_text)
    search = await service.search_jobs(query="data", limit=5)
    job = search.jobs[0]

    letter_id, letter = await service.generate_cover_letter(job_id=job.id, resume_id=resume.id)
    assert letter.generated_by == "brief"
    assert letter.brief is not None
    assert letter.resume_id == resume.id
    assert (await service.get_letter(letter_id)).job_id == job.id


async def test_cover_letter_for_an_unknown_job(service, resume_text):
    await service.parse_resume(text=resume_text)
    with pytest.raises(NotFound):
        await service.generate_cover_letter(job_id="nope")


async def test_saving_and_unsaving_a_job(service):
    search = await service.search_jobs(query="data", limit=5)
    job = search.jobs[0]
    await service.save_job(job.id, "looks good")
    assert [(j.id, note) for j, note in await service.list_saved_jobs()] == [(job.id, "looks good")]
    assert await service.unsave_job(job.id) is True


async def test_stats_reflect_the_work_done(service, resume_text):
    await service.parse_resume(text=resume_text)
    await service.search_jobs(query="data", limit=5)
    stats = await service.stats()
    assert stats["resumes"] == 1
    assert stats["jobs"] > 0


async def test_shutdown_is_safe_to_call_twice(service):
    await service.shutdown()
    await service.shutdown()
