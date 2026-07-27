"""Seniority and degree filters.

These exist because pure text similarity happily ranks "Principal ML
Architect, PhD required" as the top match for a new graduate. The similarity
is real; the recommendation is useless. Ported from v1 with the naive
``datetime.now()`` replaced by a timezone-aware clock.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from careercraft.models import Job, ParsedResume

SENIOR_TERMS = (
    "senior",
    "sr.",
    "sr ",
    "staff",
    "principal",
    "lead ",
    "manager",
    "director",
    "vp",
    "vice president",
    "head of",
    "architect",
)

_MASTERS_TERMS = (
    "master's",
    "masters degree",
    "ms degree",
    "m.s.",
    "m.sc",
    "msc",
    "ma degree",
    "m.eng",
    "meng",
    "graduate degree",
)
_PHD_TERMS = ("phd", "ph.d", "doctorate", "doctoral degree")

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

#: Degree ladder used by both the resume side and the posting side.
UNKNOWN, BACHELOR, MASTER, DOCTORATE = 0, 1, 2, 3


def job_is_senior(job: Job) -> bool:
    combined = f"{job.title} {job.level}".lower()
    return any(term in combined for term in SENIOR_TERMS)


def job_requires_masters(job: Job) -> bool:
    text = f"{job.description} {job.title}".lower()
    return any(term in text for term in _MASTERS_TERMS)


def job_requires_phd(job: Job) -> bool:
    text = f"{job.description} {job.title}".lower()
    return any(term in text for term in _PHD_TERMS)


def highest_degree(resume: ParsedResume) -> int:
    """Infer the candidate's highest degree from the education section."""

    def classify(text: str) -> int:
        lowered = text.lower()
        if any(k in lowered for k in ("phd", "ph.d", "doctor", "doctoral", "dphil")):
            return DOCTORATE
        if any(k in lowered for k in ("m.sc", "msc", "ms ", "m.s.", "master", "m.eng", "meng")):
            return MASTER
        if any(k in lowered for k in ("b.sc", "bsc", "bs ", "b.s.", "b.eng", "beng", "bachelor")):
            return BACHELOR
        return UNKNOWN

    return max(
        (classify(f"{entry.degree or ''} {entry.text}") for entry in resume.education),
        default=UNKNOWN,
    )


def graduation_year(resume: ParsedResume) -> int | None:
    years: list[int] = []
    for entry in resume.education:
        years.extend(int(y) for y in entry.years if y.isdigit())
        years.extend(int(m.group(0)) for m in _YEAR_RE.finditer(entry.text))
    return max(years) if years else None


def candidate_is_junior(resume: ParsedResume, *, now: datetime | None = None) -> bool:
    """Whether to treat the candidate as early-career.

    Deliberately conservative in one direction: any senior-sounding title in
    the work history disqualifies the label outright, because wrongly
    filtering senior roles out of a senior person's results is far more
    damaging than leaving a few senior roles in a graduate's.
    """
    titles = " ".join(entry.title.lower() for entry in resume.experience)
    if any(term in titles for term in SENIOR_TERMS):
        return False

    degree = highest_degree(resume)
    if degree >= MASTER:
        # A master's or doctorate still counts as junior only if there is
        # essentially no work history behind it.
        return len(resume.experience) <= 1

    current_year = (now or datetime.now(timezone.utc)).year
    year = graduation_year(resume)
    recently_graduated = year is not None and year >= current_year - 2
    still_studying = year is None and bool(resume.education)

    title_list = [entry.title.lower() for entry in resume.experience]
    intern_like = sum(
        any(k in t for k in ("intern", "student", "research assistant", "teaching assistant"))
        for t in title_list
    )
    mostly_intern = bool(title_list) and intern_like >= max(1, len(title_list) - 1)
    short_history = len(title_list) <= 2

    return recently_graduated or still_studying or mostly_intern or short_history


def filter_jobs(
    resume: ParsedResume,
    jobs: list[Job],
    *,
    filter_seniority: bool = True,
) -> tuple[list[Job], int]:
    """Drop postings the candidate is structurally ineligible for.

    Returns ``(kept, dropped_count)``.
    """
    if not filter_seniority:
        return list(jobs), 0

    junior = candidate_is_junior(resume)
    degree = highest_degree(resume)

    kept: list[Job] = []
    for job in jobs:
        if junior and job_is_senior(job):
            continue
        if degree <= BACHELOR and (job_requires_phd(job) or job_requires_masters(job)):
            continue
        if degree == MASTER and job_requires_phd(job):
            continue
        kept.append(job)
    return kept, len(jobs) - len(kept)
