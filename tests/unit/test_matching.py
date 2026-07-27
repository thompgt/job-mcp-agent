"""Seniority filtering and keyword ranking."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from careercraft.core.matching.heuristics import (
    candidate_is_junior,
    filter_jobs,
    highest_degree,
    job_is_senior,
    job_requires_masters,
    job_requires_phd,
)
from careercraft.core.matching.keyword import KeywordScorer
from careercraft.core.matching.service import rank_jobs
from careercraft.core.resume.parse import parse_resume_text
from careercraft.models import Job

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _job(title: str, description: str = "", **kw) -> Job:
    return Job(
        id=Job.make_id(title, kw.get("company", "Acme"), title),
        title=title,
        company=kw.get("company", "Acme"),
        description=description,
        level=kw.get("level", ""),
    )


# ------------------------------------------------------------- heuristics


@pytest.mark.parametrize(
    "title",
    ["Senior Data Engineer", "Staff Software Engineer", "Principal Architect", "Lead Analyst"],
)
def test_senior_titles_are_detected(title):
    assert job_is_senior(_job(title))


@pytest.mark.parametrize("title", ["Junior Data Analyst", "Software Engineer", "Data Analyst I"])
def test_non_senior_titles_are_not(title):
    assert not job_is_senior(_job(title))


@pytest.mark.parametrize(
    "title",
    [
        "Data Architecture Analyst",  # 'architect' is a substring of 'architecture'
        "Lead Generation Specialist",  # 'lead' is not the seniority sense here
        "Team Leader Support Associate",  # 'leader', not 'lead'
    ],
)
def test_senior_terms_are_not_matched_as_substrings(title):
    assert not job_is_senior(_job(title))


def test_the_description_does_not_decide_seniority():
    """Nearly every posting mentions senior colleagues; none of that is the role."""
    job = _job(
        "Data Analyst",
        "You will report to a senior manager and work with our principal engineers.",
    )
    assert not job_is_senior(job)


def test_the_boards_own_level_field_is_respected():
    assert job_is_senior(_job("Database Engineer", level="Senior"))


def test_degree_requirements_are_read_from_the_description():
    assert job_requires_masters(_job("Analyst", "Master's degree required."))
    assert job_requires_phd(_job("Scientist", "PhD in a quantitative field required."))
    assert not job_requires_phd(_job("Analyst", "Bachelor's degree required."))


@pytest.mark.parametrize(
    "description",
    [
        "Bachelor's degree required. Master's degree preferred.",
        "MS in a quantitative field or equivalent experience.",
        "PhD is a plus.",
        "Advanced degree (Master's) nice to have.",
        "Bachelor's or Master's degree in a related field.",
    ],
)
def test_a_preferred_degree_is_not_a_gate(description):
    """'Master's preferred' must not hide a posting from a bachelor's graduate."""
    job = _job("Data Analyst", description)
    assert not (job_requires_masters(job) or job_requires_phd(job))


def test_a_requirement_in_one_clause_survives_a_preference_in_another():
    job = _job("Research Scientist", "PhD required. Publications preferred.")
    assert job_requires_phd(job)


def test_highest_degree_ranks_the_ladder(resume_text, senior_resume_text):
    junior = parse_resume_text(resume_text)
    senior = parse_resume_text(senior_resume_text)
    assert highest_degree(senior) > highest_degree(junior)


def test_recent_graduate_is_junior(resume_text):
    assert candidate_is_junior(parse_resume_text(resume_text), now=NOW)


def test_principal_engineer_is_not_junior(senior_resume_text):
    assert not candidate_is_junior(parse_resume_text(senior_resume_text), now=NOW)


def test_filter_drops_senior_and_degree_gated_roles(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [
        _job("Junior Data Analyst"),
        _job("Data Analyst"),
        _job("Senior Machine Learning Engineer"),
        _job("Research Scientist", "PhD in machine learning required."),
    ]
    kept, dropped = filter_jobs(resume, jobs)
    titles = {j.title for j in kept}
    assert "Junior Data Analyst" in titles
    assert "Senior Machine Learning Engineer" not in titles
    assert "Research Scientist" not in titles
    assert dropped == 2


def test_filter_is_a_no_op_when_disabled(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [_job("Senior Everything Engineer")]
    kept, dropped = filter_jobs(resume, jobs, filter_seniority=False)
    assert len(kept) == 1
    assert dropped == 0


# ---------------------------------------------------------------- scoring


def test_keyword_scorer_ranks_the_relevant_job_first(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [
        _job("Pastry Chef", "Croissants, laminated dough, early mornings, kitchen brigade."),
        _job("Data Analyst", "Python, SQL, pandas and Tableau. Build ETL and dashboards."),
    ]
    scorer = KeywordScorer(jobs)
    scored = scorer.score_all(resume)
    assert scored[1][0] > scored[0][0]


def test_keyword_scorer_reports_matched_and_missing(resume_text):
    resume = parse_resume_text(resume_text)
    job = _job("Platform Engineer", "We use Python, Kubernetes and Terraform.")
    (_score, matched, missing) = KeywordScorer([job]).score_all(resume)[0]
    assert "Python" in matched
    assert {"Kubernetes", "Terraform"} <= set(missing)


def test_a_sparse_posting_does_not_beat_a_rich_one(resume_text):
    """One lucky keyword must not outrank a genuinely close match.

    Observed against the live job board: a generic listing naming a single
    skill the candidate had scored 0.58, while an ML engineering role sharing
    seven scored 0.29 — because coverage alone is 1.0 when a posting names one
    thing and you have it.
    """
    resume = parse_resume_text(resume_text)
    sparse = _job("Online Data Analyst", "Some familiarity with machine learning helps.")
    rich = _job(
        "Applied Data Scientist",
        "Python, SQL, PyTorch, AWS, Airflow, pandas and scikit-learn. "
        "Exposure to Snowflake, dbt, Databricks and BigQuery is useful.",
    )
    scores = dict(
        zip(
            [sparse.title, rich.title],
            [s for s, _, _ in KeywordScorer([sparse, rich]).score_all(resume)],
            strict=True,
        )
    )
    assert scores["Applied Data Scientist"] > scores["Online Data Analyst"]


def test_scores_stay_in_range(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [_job("A", "Python SQL"), _job("B", "Nothing relevant at all")]
    for score, _, _ in KeywordScorer(jobs).score_all(resume):
        assert 0.0 <= score <= 1.0


def test_posting_with_no_recognised_skills_still_scores(resume_text):
    """Falls back to text similarity rather than reporting a flat zero."""
    resume = parse_resume_text(resume_text)
    job = _job("Data Wrangler", "You will wrangle data and build reporting pipelines daily.")
    score, matched, _ = KeywordScorer([job]).score_all(resume)[0]
    assert matched == [] or score > 0.0
    assert score > 0.0


# ----------------------------------------------------------- rank_jobs


def test_rank_jobs_returns_matches_with_rationales(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [
        _job("Data Analyst", "Python, SQL, pandas, Tableau, ETL pipelines."),
        _job("Pastry Chef", "Croissants and laminated dough."),
    ]
    result = rank_jobs(resume, jobs, top_k=5, min_score=0.0, strategy="keyword")
    assert result.strategy_used == "keyword"
    assert result.matches
    assert all(m.rationale for m in result.matches)
    assert result.matches[0].job.title == "Data Analyst"


def test_rank_jobs_explains_an_empty_result(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [_job("Pastry Chef", "Croissants and laminated dough.")]
    result = rank_jobs(resume, jobs, min_score=0.99, strategy="keyword")
    assert result.matches == []
    assert result.notes, "an empty result must say why it is empty"
    assert any("0." in n for n in result.notes)


def test_rank_jobs_explains_a_total_filter_wipeout(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [_job("Senior Staff Principal Engineer")]
    result = rank_jobs(resume, jobs, strategy="keyword")
    assert result.matches == []
    assert result.jobs_filtered_out == 1
    assert result.notes


def test_the_rationale_admits_when_it_truncates(resume_text):
    """'Shares 7 skills: A, B, C, D, E' reads as a contradiction."""
    from careercraft.core.matching.keyword import explain

    line = explain(0.5, ["A", "B", "C", "D", "E", "F", "G"], ["X", "Y", "Z", "W", "V"])
    assert "and 2 more" in line
    assert "and 1 more" in line


def test_one_shared_skill_is_singular(resume_text):
    from careercraft.core.matching.keyword import explain

    assert "Shares 1 skill:" in explain(0.5, ["Python"], [])


def test_the_filter_note_says_why_not_just_how_many(resume_text):
    """A 90% drop rate with no reason reads as a bug."""
    resume = parse_resume_text(resume_text)
    jobs = [
        _job("Senior Data Engineer"),
        _job("Director of Analytics"),
        _job("Research Scientist", "PhD required."),
        _job("Data Analyst", "Python and SQL."),
    ]
    result = rank_jobs(resume, jobs, min_score=0.0, strategy="keyword")
    note = " ".join(result.notes)
    assert "senior or management" in note
    assert "doctorate" in note
    assert "filter_seniority=false" in note


def test_top_k_is_respected(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [_job(f"Data Analyst {i}", "Python SQL pandas") for i in range(10)]
    result = rank_jobs(resume, jobs, top_k=3, min_score=0.0, strategy="keyword")
    assert len(result.matches) == 3


def test_results_are_sorted_by_descending_score(resume_text):
    resume = parse_resume_text(resume_text)
    jobs = [
        _job("Pastry Chef", "Croissants."),
        _job("Data Analyst", "Python SQL pandas Tableau."),
        _job("Data Engineer", "Python SQL Airflow."),
    ]
    result = rank_jobs(resume, jobs, min_score=0.0, strategy="keyword")
    scores = [m.score for m in result.matches]
    assert scores == sorted(scores, reverse=True)
