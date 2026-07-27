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


def test_degree_requirements_are_read_from_the_description():
    assert job_requires_masters(_job("Analyst", "Master's degree required."))
    assert job_requires_phd(_job("Scientist", "PhD in a quantitative field required."))
    assert not job_requires_phd(_job("Analyst", "Bachelor's degree required."))


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
