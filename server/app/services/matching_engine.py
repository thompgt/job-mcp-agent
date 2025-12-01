# server/app/services/matching_engine.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import re

try:
    import numpy as np
except ImportError:  # keep module importable even if numpy is missing
    np = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None  # type: ignore


# =========================
# global encoder
# =========================
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


# =========================
# text formatting helpers
# =========================
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
        if isinstance(proj, dict):
            name = (proj.get("name") or "").strip()
            highlights = proj.get("highlights") or []
        else:
            name = str(proj)
            highlights = []
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


# =========================
# seniority + degree heuristics
# =========================
_SENIOR_TERMS = (
    "senior", "sr.", "sr ", "staff", "principal", "lead", "manager",
    "director", "vp", "vice president", "head", "architect"
)

_JUNIOR_TERMS = (
    "junior", "intern", "internship", "graduate", "entry", "entry level"
)

_ADV_MASTERS_TERMS = (
    "master's", "masters degree", "ms degree", "m.s.", "m.sc", "msc", "ma degree",
    "m.eng", "meng", "graduate degree"
)

_ADV_PHD_TERMS = (
    "phd", "ph.d", "doctorate", "doctoral degree"
)


def _job_is_obviously_senior(job: Dict[str, Any]) -> bool:
    """Return True if the job clearly looks senior-level."""
    title = (job.get("jobTitle") or job.get("title") or "").lower()
    level = (job.get("jobLevel") or "").lower()
    combined = f"{title} {level}"
    return any(term in combined for term in _SENIOR_TERMS)


def _job_requires_masters(job: Dict[str, Any]) -> bool:
    """Heuristic: does the job likely require at least a Master's degree?"""
    text = (
        (job.get("jobDescription") or "")
        + " "
        + (job.get("description") or "")
        + " "
        + (job.get("title") or "")
    ).lower()
    return any(term in text for term in _ADV_MASTERS_TERMS)


def _job_requires_phd(job: Dict[str, Any]) -> bool:
    """Heuristic: does the job likely require a PhD?"""
    text = (
        (job.get("jobDescription") or "")
        + " "
        + (job.get("description") or "")
        + " "
        + (job.get("title") or "")
    ).lower()
    return any(term in text for term in _ADV_PHD_TERMS)


def _highest_degree_level(resume: Dict[str, Any]) -> int:
    """
    Infer highest degree level from resume education.

    Returns:
        0 = unknown / less than bachelor
        1 = bachelor
        2 = master
        3 = phd or above
    """
    education = resume.get("education") or []
    level = 0

    def classify(text: str) -> int:
        txt = text.lower()
        if any(k in txt for k in ("phd", "ph.d", "doctor", "doctoral", "dphil")):
            return 3
        if any(k in txt for k in ("m.sc", "msc", "ms ", "m.s.", "master", "ma ", "m.eng", "meng")):
            return 2
        if any(k in txt for k in ("b.sc", "bsc", "bs ", "b.s.", "b.eng", "beng", "bachelor", "ba ")):
            return 1
        return 0

    for ed in education:
        deg = ""
        if isinstance(ed, dict):
            deg = (ed.get("degree") or ed.get("text") or "").lower()
        else:
            deg = str(ed).lower()
        level = max(level, classify(deg))
    return level


def _graduation_year_estimate(resume: Dict[str, Any]) -> Optional[int]:
    """Approximate most recent graduation year from education entries."""
    education = resume.get("education") or []
    years: List[int] = []
    year_re = re.compile(r"(19|20)\d{2}")
    for ed in education:
        ys = None
        if isinstance(ed, dict):
            if isinstance(ed.get("years"), list) and ed["years"]:
                ys = ed["years"]
        if ys:
            for y in ys:
                try:
                    years.append(int(y))
                except Exception:
                    pass
        else:
            txt = ""
            if isinstance(ed, dict):
                txt = ed.get("text") or ""
            else:
                txt = str(ed)
            for m in year_re.findall(txt):
                try:
                    years.append(int("".join(m)))
                except Exception:
                    pass
    return max(years) if years else None


def _candidate_looks_junior(resume: Dict[str, Any]) -> bool:
    """
    Heuristic: treat candidate as 'junior' if they are recently graduated
    and/or mostly have internship / early-career roles.
    """
    experience = resume.get("experience") or []
    titles = [str(e.get("title") or "").lower() for e in experience]

    # If any senior/staff/lead terms present, not junior.
    if any(term in " ".join(titles) for term in _SENIOR_TERMS):
        return False

    # Degree + grad year based heuristic
    degree_level = _highest_degree_level(resume)
    grad_year = _graduation_year_estimate(resume)
    current_year = datetime.now().year

    recently_graduated = grad_year is not None and grad_year >= current_year - 2
    still_studying = grad_year is None  # no grad year but has education entries

    # Titles heuristic: mostly internships / assistant / student-like roles
    intern_like = sum(
        any(k in t for k in ("intern", "student", "research assistant", "teaching assistant"))
        for t in titles
    )

    mostly_intern = intern_like >= max(1, len(titles) - 1)

    # If they only have 0–2 roles and no senior keywords, treat as junior.
    short_history = len(titles) <= 2

    if degree_level <= 1 and (recently_graduated or still_studying or mostly_intern or short_history):
        return True

    return False


# =========================
# similarity computation
# =========================
def _cosine_similarity_matrix(job_vecs: np.ndarray, resume_vec: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between each job vector and the resume vector."""
    # job_vecs: (n_jobs, dim), resume_vec: (dim,)
    # Normalize just in case (if not already normalized by encoder)
    job_norms = np.linalg.norm(job_vecs, axis=1, keepdims=True)
    resume_norm = np.linalg.norm(resume_vec)
    denom = job_norms * resume_norm
    denom[denom == 0.0] = 1e-8
    sims = (job_vecs @ resume_vec) / denom
    return sims


def _fallback_keyword_score(resume: Dict[str, Any], job: Dict[str, Any]) -> float:
    """
    Simple backup scorer if sentence-transformers isn't available:
    overlap between resume skills and job text.
    """
    skills = {s.lower() for s in (resume.get("skills") or [])}
    if not skills:
        return 0.0

    text = (_job_to_text(job) or "").lower()
    matches = sum(1 for s in skills if s in text)
    return matches / float(len(skills))


# =========================
# public API
# =========================
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
    (sentence-transformers) plus seniority and degree heuristics.

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
    candidate_is_junior = _candidate_looks_junior(resume)
    degree_level = _highest_degree_level(resume)

    use_embeddings = SentenceTransformer is not None and np is not None

    # Pre-filter jobs according to heuristics (seniority, degree)
    filtered_jobs: List[Dict[str, Any]] = []
    for job in jobs:
        # Seniority filtering
        if filter_senior_for_grads and candidate_is_junior and _job_is_obviously_senior(job):
            continue

        # Degree requirement filtering
        if degree_level <= 1:
            # Only undergrad / below
            if _job_requires_phd(job) or _job_requires_masters(job):
                continue
        elif degree_level == 2:
            # Master's – still filter explicit PhD-only roles
            if _job_requires_phd(job):
                continue

        filtered_jobs.append(job)

    if not filtered_jobs:
        return []

    ranked: List[Tuple[Dict[str, Any], float]] = []

    if use_embeddings:
        # --- Fast path: batch embeddings for speed ---
        encoder = _get_encoder(model_name)
        resume_text = _resume_to_text(resume)
        resume_vec = encoder.encode(resume_text, convert_to_numpy=True)

        job_texts = [_job_to_text(job) for job in filtered_jobs]
        job_vecs = encoder.encode(job_texts, convert_to_numpy=True)

        sims = _cosine_similarity_matrix(job_vecs, resume_vec)
        # Ensure sims is a 1D float array
        import numpy as _np  # local alias to avoid confusion
        sims = _np.asarray(sims, dtype=float).reshape(-1)

        for job, score in zip(filtered_jobs, sims):
            score_val = float(score)  # now guaranteed scalar
            if score_val >= min_similarity:
                job_with_score = dict(job)
                job_with_score["similarity"] = score_val
                ranked.append((job_with_score, score_val))


    else:
        # --- Fallback: simple keyword overlap ---
        for job in filtered_jobs:
            score = _fallback_keyword_score(resume, job)
            if score >= min_similarity:
                job_with_score = dict(job)
                job_with_score["similarity"] = float(score)
                ranked.append((job_with_score, score))

    ranked.sort(key=lambda t: t[1], reverse=True)
    return [job for job, _ in ranked[:top_k]]


# =========================
# CLI helper
# =========================
if __name__ == "__main__":
    """
    Example usage for local testing:

        python -m server.app.services.matching_engine /path/to/resume.pdf

    Make sure you're running this from the project root and that
    `sentence-transformers` and `numpy` are installed.
    """
    import argparse
    from pathlib import Path
    import json

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
