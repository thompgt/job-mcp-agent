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
    "sr",
    "staff",
    "principal",
    "lead",
    "manager",
    "director",
    "vp",
    "vice president",
    "head of",
    "architect",
)

#: Matched on word boundaries rather than as substrings. Plain ``in`` checks
#: made "architect" fire on "architecture" and "lead" on "lead time", so roles
#: that were not senior at all were dropped from a graduate's results with no
#: way to see why.
_SENIOR_RE = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(re.escape(t) for t in SENIOR_TERMS) + r")(?![A-Za-z])",
    re.IGNORECASE,
)

#: Phrases where a seniority word is doing a different job. Word boundaries
#: cannot separate "Lead Generation Specialist" — an entry-level sales role —
#: from "Lead Data Engineer", so the phrase is removed before matching.
_NOT_SENIORITY = (
    "lead generation",
    "lead gen",
    "leads",
    "solution architect intern",
    "account manager assistant",
)

_MASTERS_TERMS = (
    "master's",
    "masters degree",
    "master's degree",
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

#: Phrases that turn a stated degree into a preference rather than a gate.
#: "Master's degree preferred" and "MS or equivalent experience" are not
#: reasons to hide a posting from someone with a bachelor's — treating them as
#: such was dropping ordinary analyst roles from a new graduate's results.
_SOFTENERS = (
    "preferred",
    "prefer ",
    "a plus",
    "plus:",
    "nice to have",
    "nice-to-have",
    "bonus",
    "desirable",
    "ideally",
    "or equivalent",
    "equivalent experience",
    "equivalent practical",
    "advantage",
)

#: A bachelor's named alongside the higher degree means the higher one is an
#: alternative, not a floor.
_BACHELOR_TERMS = ("bachelor", "b.s.", "bs degree", "b.sc", "bsc", "undergraduate degree")

_SENTENCE_SPLIT = re.compile(r"[.;\n•]")

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

#: Degree ladder used by both the resume side and the posting side.
UNKNOWN, BACHELOR, MASTER, DOCTORATE = 0, 1, 2, 3


def job_is_senior(job: Job) -> bool:
    """Whether the title or the board's own level marks this as senior.

    The description is deliberately not consulted: almost every posting
    mentions senior colleagues, senior stakeholders or a senior leadership
    team, and none of that says anything about the role being advertised.
    """
    combined = f"{job.title} {job.level}".lower()
    for phrase in _NOT_SENIORITY:
        combined = combined.replace(phrase, " ")
    return bool(_SENIOR_RE.search(combined))


def _demands_degree(text: str, terms: tuple[str, ...]) -> bool:
    """Whether ``text`` makes one of ``terms`` a requirement, not a preference.

    Checked one clause at a time. A posting routinely says "Bachelor's degree
    required; Master's preferred" in a single sentence, and reading the whole
    description as one blob turns that into a hard master's gate.
    """
    lowered = text.lower()
    for clause in _SENTENCE_SPLIT.split(lowered):
        if not any(term in clause for term in terms):
            continue
        if any(soft in clause for soft in _SOFTENERS):
            continue
        if any(bachelor in clause for bachelor in _BACHELOR_TERMS):
            continue  # named as one option among several
        return True
    return False


def job_requires_masters(job: Job) -> bool:
    return _demands_degree(f"{job.title}. {job.description}", _MASTERS_TERMS)


def job_requires_phd(job: Job) -> bool:
    return _demands_degree(f"{job.title}. {job.description}", _PHD_TERMS)


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
    titles = " ".join(entry.title for entry in resume.experience)
    if _SENIOR_RE.search(titles):
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
    kept, dropped = filter_jobs_explained(resume, jobs, filter_seniority=filter_seniority)
    return kept, sum(dropped.values())


def filter_jobs_explained(
    resume: ParsedResume,
    jobs: list[Job],
    *,
    filter_seniority: bool = True,
) -> tuple[list[Job], dict[str, int]]:
    """As :func:`filter_jobs`, but with a breakdown of why postings went.

    On a real search this filter can remove most of the pool — a query for
    "data" returns a great many Senior and Director roles — and "46 filtered
    out" with no reason reads like a bug. The breakdown is what makes the
    number believable, and tells the user whether to turn the filter off.
    """
    if not filter_seniority:
        return list(jobs), {}

    junior = candidate_is_junior(resume)
    degree = highest_degree(resume)

    kept: list[Job] = []
    dropped: dict[str, int] = {}
    for job in jobs:
        reason: str | None = None
        if junior and job_is_senior(job):
            reason = "senior or management roles"
        elif degree <= BACHELOR and job_requires_phd(job):
            reason = "roles requiring a doctorate"
        elif degree <= BACHELOR and job_requires_masters(job):
            reason = "roles requiring a master's"
        elif degree == MASTER and job_requires_phd(job):
            reason = "roles requiring a doctorate"

        if reason is None:
            kept.append(job)
        else:
            dropped[reason] = dropped.get(reason, 0) + 1
    return kept, dropped
