from __future__ import annotations
from typing import Dict, Any, Optional
from langchain.chat_models import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage

def _format_resume_for_prompt(resume: Dict[str, Any]) -> str:
    """Convert a parsed résumé dictionary into a human‑readable summary.

    Parameters
    ----------
    resume : dict
        Structured résumé data as returned by
        :func:`server.app.services.resume_parser.parse_resume_file`.

    Returns
    -------
    str
        A formatted string suitable for embedding in a prompt.
    """
    lines: list[str] = []
    profile = resume.get("profile")
    if profile:
        lines.append(f"Profile: {profile}")

    skills = resume.get("skills")
    if skills:
        lines.append("Skills: " + ", ".join(sorted(skills)))

    experience = resume.get("experience")
    if experience:
        lines.append("Experience:")
        # Join each bullet on its own line for readability
        for exp in experience:
            lines.append(f"- {exp}")

    education = resume.get("education")
    if education:
        lines.append("Education: " + "; ".join(str(e) for e in education))

    projects = resume.get("projects")
    if projects:
        lines.append("Projects: " + "; ".join(str(p) for p in projects))

    return "\n".join(lines)

def _format_job_for_prompt(job: Dict[str, Any]) -> str:
    """Convert a job dictionary into a human‑readable summary.

    Parameters
    ----------
    job : dict
        Raw job posting dictionary.  Field names from different APIs are
        normalised where possible (e.g. ``title`` or ``jobTitle``).

    Returns
    -------
    str
        A formatted string suitable for embedding in a prompt.
    """
    title = job.get("title") or job.get("jobTitle") or job.get("name") or "Unknown role"
    company = job.get("company") or job.get("companyName") or job.get("org") or "Unknown company"
    location = job.get("location") or job.get("jobGeo") or job.get("job_location") or "Unknown location"
    description = job.get("description") or job.get("jobDescription") or job.get("desc") or ""

    parts = [
        f"Title: {title}",
        f"Company: {company}",
        f"Location: {location}",
    ]
    if description:
        parts.append("Description: " + description)
    return "\n".join(parts)
