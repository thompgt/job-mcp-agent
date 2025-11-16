# server/app/services/matching_engine.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple

import math

try:
    import numpy as np
except ImportError:  # very unlikely, but keeps module importable
    np = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore

# Lazy-loaded global encoder
_ENCODER: Optional[SentenceTransformer] = None


def _get_encoder(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    """Lazy-load and cache the sentence-transformers model."""
    global _ENCODER
    if _ENCODER is None:
        if SentenceTransformer is None:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install it via `pip install sentence-transformers`."
            )
        _ENCODER = SentenceTransformer(model_name)
    return _ENCODER


# ---------------------------------------------------------------------------
# Text formatting helpers for embeddings
# ---------------------------------------------------------------------------

def _resume_to_text(resume: Dict[str, Any]) -> str:
    """Convert parsed resume dict into a single text string for embeddings."""
    parts: List[str] = []

    # Name
    if resume.get("name"):
        parts.append(f"Name: {resume['name']}")

    # Skills
    skills = resume.get("skills") or []
    if skills:
        parts.append("Skills: " + ", ".join(sorted(skills)))

    # Experience – compress into short job summaries
    experience = resume.get("experience") or []
    exp_snippets: List[str] = []
    for role in experience:
        org = (role.get("organization") or "").strip()
        title = (role.get("title") or "").strip()
        period = (role.get("period") or "").strip()
        highlights = role.get("highlights") or []

        header_bits = [b for b in [title, org, period] if b]
        header = " at ".join(header_bits[:2]) if header_bits else ""
        if len(header_bits) > 2:
            header += f" ({header_bits[2]})"

        # take first 1–2 bullets max; keep them short-ish
        bullet_text = " ".join(h.strip() for h in highlights[:2])
        snippet = " ".join(s for s in [header, bullet_text] if s)
        if snippet:
            exp_snippets.append(snippet)

    if exp_snippets:
        parts.append("Experience: " + " | ".join(exp_snippets))

    # Education
    education = resume.get("education") or []
    edu_bits: List[str] = []
    for ed in education:
        if isinstance(ed, dict):
            txt = ed.get("text") or ""
        else:
            txt = str(ed)
        txt = txt.strip()
        if txt:
            edu_bits.append(txt)
    if edu_bits:
        parts.append("Education: " + " | ".join(edu_bits))

    # Projects – keep very short
    projects = resume.get("projects") or []
    proj_bits: List[str] = []
    for proj in projects[:3]:
        name = (proj.get("name") or "").strip() if isinstance(proj, dict) else str(proj)
        highlights = proj.get("highlights") if isinstance(proj, dict) else []
        if name:
            snippet = name
            if highlights:
                snippet += " – " + highlights[0]
            proj_bits.append(snippet)
    if proj_bits:
        parts.append("Projects: " + " | ".join(proj_bits))

    return "\n".join(parts)


def _job_to_text(job: Dict[str, Any]) -> str:
    """Convert a job dict from Jobicy/other APIs into text for embeddings."""
    title = job.get("jobTitle") or job.get("title") or job.get("name") or ""
    company = job.get("companyName") or job.get("company") or job.get("org") or ""
    level = job.get("jobLevel") or ""
    job_type = job.get("jobType") or job.get("type") or ""
    geo = job.get("jobGeo") or job.get("location") or job.get("job_location") or ""
    desc = job.get("jobDescription") or job.get("description") or job.get("jobExcerpt") or ""

    fields = [
        f"Title: {title}" if title else "",
        f"Company: {company}" if company else "",
        f"Level: {level}" if level else "",
        f"Type: {job_type}" if job_type else "",
        f"Location: {geo}" if geo else "",
        f"Description: {desc}" if desc else "",
    ]
    return "\n".join([f for f in fields if f])


# ---------------------------------------------------------------------------
# Seniority heuristics
# ---------------------------------------------------------------------------

_SENIOR_TERMS = (
    "senior", "sr.", "sr ", "staff", "principal", "lead", "manager",
    "director", "vp", "vice president", "head", "architect"
)

_JUNIOR_TERMS = (
    "junior", "intern", "internship", "graduate", "entry", "entry level", "new graduate", "analyst"
)


def _job_is_obviously_senior(job: Dict[str, Any]) -> bool:
    """Return True if the job clearly looks senior-level."""
    title = (job.get("jobTitle") or job.get("title") or "").lower()
    level = (job.get("jobLevel") or "").lower()
    combined = f"{title} {level}"
    return any(term in combined for term in _SENIOR_TERMS)


def _job_is_junior_friendly(job: Dict[str, Any]) -> bool:
    """Return True if the job explicitly looks junior or open-level."""
    title = (job.get("jobTitle") or job.get("title") or "").lower()
    level = (job.get("jobLevel") or "").lower()
    combined = f"{title} {level}"

    if any(term in combined for term in _JUNIOR_TERMS):
        return True

    # Many feeds use "Any" or blank level for open-level roles
    if not level or level.strip().lower() in {"any", "mid", "middle"}:
        return True

    return False


def _candidate_looks_junior(resume: Dict[str, Any]) -> bool:
    """Heuristic: treat as 'junior' if mostly internships or short experience."""
    experience = resume.get("experience") or []
    if not experience:
        return True

    titles = [str(e.get("title") or "").lower() for e in experience]
    # if most titles contain 'intern' or 'student' etc, treat as junior
    intern_like = sum(
        any(k in t for k in ("intern", "student", "research assistant", "teaching assistant"))
        for t in titles
    )
    if intern_like >= max(1, len(titles) - 1):
        return True

    # crude: if <= 2 roles and no senior keywords, still junior
    if len(titles) <= 2 and not any(term in " ".join(titles) for term in _SENIOR_TERMS):
        return True

    return False


# ---------------------------------------------------------------------------
# Similarity computation
# ---------------------------------------------------------------------------

def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Compute cosine similarity between two 1D vectors."""
    denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b))
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def _fallback_keyword_score(resume: Dict[str, Any], job: Dict[str, Any]) -> float:
    """
    Very simple backup scorer if sentence-transformers isn't available:
    overlap between resume skills and job text.
    """
    skills = {s.lower() for s in (resume.get("skills") or [])}
    if not skills:
        return 0.0

    text = (_job_to_text(job) or "").lower()
    matches = sum(1 for s in skills if s in text)
    return matches / float(len(skills))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def rank_jobs_for_resume(
    resume: Dict[str, Any],
    jobs: List[Dict[str, Any]],
    *,
    top_k: int = 10,
    min_similarity: float = 0.25,
    filter_senior_for_grads: bool = True,
    model_name: str = "all-MiniLM-L6-v2",
) -> List[Dict[str, Any]]:
    """
    Rank a list of jobs for a given parsed resume using semantic similarity
    (sentence-transformers) plus some seniority heuristics.

    Parameters
    ----------
    resume : dict
        Parsed resume from `parse_resume_file`.
    jobs : list of dict
        Raw jobs from `get_data.fetch_jobs()` or the in-memory queue.
    top_k : int
        Number of top jobs to return.
    min_similarity : float
        Minimum cosine similarity threshold to keep a job.
    filter_senior_for_grads : bool
        If True, and the candidate looks junior, filter out obviously
        senior jobs (e.g. "Senior Software Engineer", jobLevel="Senior").
    model_name : str
        Sentence-transformers model name.

    Returns
    -------
    list of dict
        The top-k job dicts, each augmented with a `similarity` field.
    """
    # Optional seniority filter
    candidate_is_junior = _candidate_looks_junior(resume)

    # Try semantic embeddings first, fall back to keyword scoring if unavailable.
    use_embeddings = SentenceTransformer is not None and np is not None

    # Precompute resume representation
    if use_embeddings:
        encoder = _get_encoder(model_name)
        resume_text = _resume_to_text(resume)
        resume_vec = encoder.encode(resume_text)
    else:
        resume_vec = None  # type: ignore

    ranked: List[Tuple[Dict[str, Any], float]] = []

    for job in jobs:
        # Filter out obviously senior jobs for junior candidates
        if filter_senior_for_grads and candidate_is_junior and _job_is_obviously_senior(job):
            continue

        if use_embeddings:
            job_text = _job_to_text(job)
            job_vec = encoder.encode(job_text)
            score = _cosine_similarity(resume_vec, job_vec)
        else:
            score = _fallback_keyword_score(resume, job)

        if score >= min_similarity:
            job_with_score = dict(job)
            job_with_score["similarity"] = float(score)
            ranked.append((job_with_score, score))

    # Sort by similarity descending and keep top_k
    ranked.sort(key=lambda t: t[1], reverse=True)
    return [job for job, _ in ranked[:top_k]]


# ---------------------------------------------------------------------------
# Dev / CLI helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Example usage for local testing:

        python -m server.app.services.matching_engine /path/to/resume.pdf

    Make sure you're running this from the project root and that
    `sentence-transformers` is installed.
    """
    import argparse
    import json
    from pathlib import Path
    from server.app.services.resume_parser import parse_resume_file
    from get_data import fetch_jobs  # top-level get_data.py

    ap = argparse.ArgumentParser()
    ap.add_argument("resume", help="Path to resume file (pdf/docx/txt)")
    ap.add_argument("--count", type=int, default=50, help="Number of jobs to fetch")
    ap.add_argument("--top-k", type=int, default=10, help="Number of jobs to display")
    args = ap.parse_args()

    resume_path = Path(args.resume)
    print(f"Parsing resume: {resume_path}")
    resume_data = parse_resume_file(resume_path)

    print(f"Fetching {args.count} jobs from API...")
    jobs = fetch_jobs(count=args.count)

    print("Scoring jobs...")
    matches = rank_jobs_for_resume(
        resume_data,
        jobs,
        top_k=args.top_k,
        min_similarity=0.25,
        filter_senior_for_grads=True,
    )

    print(f"\nTop {len(matches)} matches:\n")
    for j in matches:
        title = j.get("jobTitle") or j.get("title")
        company = j.get("companyName") or j.get("company")
        geo = j.get("jobGeo") or j.get("location")
        level = j.get("jobLevel")
        sim = j.get("similarity")
        print(f"- {title} at {company} — {geo} | level={level} | similarity={sim:.3f}")

