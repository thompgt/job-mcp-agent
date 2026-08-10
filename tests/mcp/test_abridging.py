"""List-shaped tool results must not flood the host model's context.

``match_jobs(top_k=50)`` returned fifty postings at full length — well over a
hundred thousand characters of scraped board text in a single tool result.
These tests pin the preview, and pin that ``get_job`` still hands back the
whole thing, because a truncation the caller cannot undo would be worse than
the flood.
"""

from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP

from careercraft.adapters.llm import NullProvider
from careercraft.core.jobs.base import JobProvider, JobQuery
from careercraft.mcp.server import _LIST_DESCRIPTION_CHARS, build_server
from careercraft.models import Job
from careercraft.service import CareerCraftService

LONG = "Responsibilities include maintaining the data platform. " * 200


class VerboseProvider(JobProvider):
    """A board whose postings are as long as real ones are."""

    name = "verbose"

    async def search(self, query: JobQuery) -> list[Job]:
        return [
            Job(
                id=Job.make_id(f"Engineer {i}", "Verbose Corp", f"https://v.test/{i}"),
                title=f"Engineer {i}",
                company="Verbose Corp",
                location="Remote",
                description=LONG,
                url=f"https://v.test/{i}",
                source="verbose",
            )
            for i in range(query.limit)
        ]


@pytest.fixture
async def verbose_client(settings, store):
    svc = CareerCraftService(
        settings, store=store, job_provider=VerboseProvider(), llm=NullProvider()
    )
    await svc.startup()
    server: FastMCP = build_server(settings, service=svc)
    async with Client(server) as c:
        yield c
    await svc.shutdown()


def _is_preview(text: str) -> bool:
    return len(text) < len(LONG) and "get_job" in text


async def test_search_jobs_returns_previews_not_whole_postings(verbose_client):
    result = await verbose_client.call_tool("search_jobs", {"query": "data", "limit": 10})

    assert result.data.jobs
    for job in result.data.jobs:
        assert _is_preview(job.description)
        # The preview plus its marker, and nothing like the 11k-character original.
        assert len(job.description) < _LIST_DESCRIPTION_CHARS + 100


async def test_match_jobs_does_not_dump_fifty_descriptions(verbose_client, resume_text):
    parsed = await verbose_client.call_tool("parse_resume", {"text": resume_text})
    result = await verbose_client.call_tool(
        "match_jobs",
        {"resume_id": parsed.data.id, "query": "data", "top_k": 50, "min_score": 0.0},
    )

    assert result.data.matches
    total = sum(len(m.job.description) for m in result.data.matches)
    assert total < 50 * (_LIST_DESCRIPTION_CHARS + 100)
    assert all(_is_preview(m.job.description) for m in result.data.matches)


async def test_get_job_still_returns_the_full_description(verbose_client):
    search = await verbose_client.call_tool("search_jobs", {"query": "data", "limit": 1})
    job_id = search.data.jobs[0].id

    full = await verbose_client.call_tool("get_job", {"job_id": job_id})
    assert full.data.description == LONG


async def test_the_recent_jobs_resource_is_abridged_too(verbose_client):
    await verbose_client.call_tool("search_jobs", {"query": "data", "limit": 10})

    contents = await verbose_client.read_resource("careercraft://jobs/recent")
    text = contents[0].text
    assert LONG not in text
    assert "get_job" in text


async def test_a_short_description_is_left_exactly_as_it_is(verbose_client, resume_text):
    """Only postings that overrun are touched — no marker on a short one."""
    from careercraft.mcp.server import _abridge

    short = Job(id="x", title="T", company="C", description="Short and complete.")
    assert _abridge(short) is short
