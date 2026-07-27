"""Cover letter generation and its two fallbacks."""

from __future__ import annotations

import pytest

from careercraft.adapters.llm import NullProvider
from careercraft.core.letters.generator import build_brief, generate_letter, render_template
from careercraft.core.letters.prompts import build_messages
from careercraft.core.resume.parse import parse_resume_text
from careercraft.errors import ProviderError
from careercraft.models import Job

JOB = Job(
    id="abc123",
    title="Data Analyst",
    company="Northwind Trading",
    description=(
        "Northwind Trading is hiring a Data Analyst. You will build ETL pipelines in "
        "Python, model data in SQL, and ship dashboards in Tableau. We care about "
        "reproducibility and clear writing. Kubernetes experience is a plus. "
        "Northwind Trading is an equal opportunity employer."
    ),
)


@pytest.fixture
def resume(resume_text):
    return parse_resume_text(resume_text)


class _StubLLM:
    """A provider that returns a fixed body."""

    name = "stub"

    def __init__(self, body: str = "Dear Hiring Manager,\n\nI am a great fit.\n\nJane") -> None:
        self.body = body
        self.calls: list[list[dict]] = []

    async def is_available(self) -> bool:
        return True

    async def complete(self, messages, *, model=None, temperature=0.7, max_tokens=None) -> str:
        self.calls.append(messages)
        return self.body

    def stream(self, messages, **kw):  # pragma: no cover - unused here
        raise NotImplementedError


# ------------------------------------------------------------------ brief


def test_brief_is_grounded_in_both_documents(resume):
    brief = build_brief(resume, JOB, tone="professional", length="medium")
    assert brief.company == "Northwind Trading"
    assert brief.role == "Data Analyst"
    assert brief.themes
    assert brief.evidence
    assert brief.paragraph_plan


def test_brief_evidence_comes_from_the_resume(resume):
    brief = build_brief(resume, JOB, tone="professional", length="medium")
    blob = " ".join(brief.evidence).lower()
    assert "acme" in blob or "etl" in blob or "tableau" in blob


def test_company_hooks_skip_legal_boilerplate(resume):
    brief = build_brief(resume, JOB, tone="professional", length="medium")
    assert not any("equal opportunity" in hook.lower() for hook in brief.company_hooks)


def test_themes_use_word_boundaries(resume):
    """'ai' inside 'Airflow' must not imply a machine-learning theme."""
    job = Job(
        id="x",
        title="Pipeline Engineer",
        company="Acme",
        description="Airflow, dbt and Snowflake. Maintain the warehouse.",
    )
    bare = parse_resume_text("SKILLS\nAirflow, SQL\n")
    brief = build_brief(bare, job, tone="professional", length="medium")
    assert not any("machine learning" in t.lower() for t in brief.themes)


# --------------------------------------------------------------- template


def test_template_mentions_the_role_and_company(resume):
    text = render_template(resume, JOB, tone="professional", length="medium")
    assert "Data Analyst" in text
    assert "Northwind Trading" in text
    assert len(text.split()) > 60


def test_template_length_tracks_the_length_setting(resume):
    short = render_template(resume, JOB, tone="concise", length="short")
    long = render_template(resume, JOB, tone="professional", length="long")
    assert len(long.split()) >= len(short.split())


# --------------------------------------------------------------- prompts


def test_prompt_names_matched_and_missing_skills(resume):
    messages = build_messages(
        resume,
        JOB,
        matched_skills=["Python", "SQL"],
        missing_skills=["Kubernetes"],
    )
    blob = "\n".join(m["content"] for m in messages)
    assert "Python" in blob
    assert "Kubernetes" in blob
    assert "do not claim" in blob.lower() or "not claim" in blob.lower()


def test_prompt_truncates_a_huge_description(resume):
    job = JOB.model_copy(update={"description": "x " * 20000})
    messages = build_messages(resume, job)
    assert len("\n".join(m["content"] for m in messages)) < 20000


# ------------------------------------------------------------ generation


async def test_uses_the_model_when_one_is_available(resume):
    llm = _StubLLM()
    letter = await generate_letter(resume, JOB, provider=llm)
    assert letter.generated_by == "ollama"
    assert letter.text == llm.body
    assert letter.word_count > 0
    assert letter.job_id == JOB.id
    assert llm.calls, "the provider should actually have been called"


async def test_falls_back_to_a_brief_when_no_model_is_reachable(resume):
    letter = await generate_letter(resume, JOB, provider=NullProvider(), allow_brief=True)
    assert letter.generated_by == "brief"
    assert letter.text is None
    assert letter.brief is not None
    assert letter.brief.paragraph_plan


async def test_falls_back_to_a_template_when_briefs_are_declined(resume):
    letter = await generate_letter(resume, JOB, provider=NullProvider(), allow_brief=False)
    assert letter.generated_by == "template"
    assert letter.text
    assert "Northwind Trading" in letter.text


async def test_a_failing_model_degrades_rather_than_raising(resume):
    class _Broken(_StubLLM):
        async def complete(self, messages, **kw):
            raise ProviderError("Ollama died mid-request.", remedy="Restart it.")

    letter = await generate_letter(resume, JOB, provider=_Broken(), allow_brief=True)
    assert letter.generated_by in {"brief", "template"}


async def test_an_empty_model_response_is_not_returned_as_a_letter(resume):
    letter = await generate_letter(resume, JOB, provider=_StubLLM("   \n  "), allow_brief=True)
    assert letter.generated_by != "ollama"
