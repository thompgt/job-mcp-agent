"""Prompt construction for cover letters.

The instruction set is carried over from v1 largely intact — it was tuned
against real output and it works. What is new is that the resume and posting
summaries are built from typed models, and that the "here is what to draw on"
section now includes the *matched* and *missing* skills, which is the single
biggest lever on whether the letter says something specific.
"""

from __future__ import annotations

from careercraft.llm import ChatMessage
from careercraft.models import Job, Length, ParsedResume, Tone

TONE_GUIDANCE: dict[str, str] = {
    "professional": "Maintain a standard, respectful, balanced professional tone.",
    "enthusiastic": (
        "Use a warm, energetic tone that conveys genuine excitement about the company "
        "and the role, without hyperbole."
    ),
    "concise": "Be direct. Cut every sentence that does not carry information.",
    "academic": (
        "Use a formal register, foregrounding research, methodology and theoretical grounding."
    ),
}

LENGTH_GUIDANCE: dict[str, str] = {
    "short": "Write 1-2 paragraphs, at most 200 words.",
    "medium": "Write 3-4 paragraphs, around 350 words.",
    "long": "Write 4-5 paragraphs, around 550 words.",
}

_RULES = """\
1. Identify two or three core themes in the candidate's background (research ability,
   engineering rigour, quantitative analysis, collaboration, ownership) and organise the
   letter around them.
2. Merge related roles into coherent paragraphs. Do not walk through the resume job by job.
3. Paraphrase. Never copy a resume bullet verbatim.
4. You may explain how a skill was applied or what it led to, but invent no new facts,
   employers, dates, metrics or credentials.
5. Vary sentence openings; avoid starting successive paragraphs with "As a".
6. Use only the skills that matter for this posting rather than listing everything.
7. Open with "Dear Hiring Manager," unless a specific name is supplied.
8. Do not put the candidate's email, phone or LinkedIn in the body.
9. Do not open with "My name is". Start with motivation and fit.
10. Draw two or three concrete details out of the job description — the product, the team,
    the mission, the stack — and weave them in naturally. If the description is generic,
    keep this paragraph general rather than inventing specifics.
11. Close with a brief, concrete call to action.
12. Output only the letter itself. No preamble, no commentary, no markdown headings."""


def summarize_resume(resume: ParsedResume) -> str:
    """Condense the resume for the prompt.

    Free-text profile and objective sections are omitted on purpose: they are
    usually generic, and including them reliably makes models echo the fluff
    back instead of writing something specific.
    """
    parts: list[str] = []
    if resume.name:
        parts.append(f"Candidate: {resume.name}")
    if resume.skills:
        shown = resume.skills[:20]
        suffix = ", ..." if len(resume.skills) > 20 else ""
        parts.append("Skills: " + ", ".join(shown) + suffix)

    if resume.experience:
        parts.append("Experience:")
        for role in resume.experience[:5]:
            header = " at ".join(b for b in (role.title, role.organization) if b)
            if role.period:
                header = f"{header} ({role.period})" if header else role.period
            body = " ".join(h.strip() for h in role.highlights[:2])
            parts.append(f"- {header}: {body}" if body else f"- {header}")

    if resume.education:
        parts.append("Education: " + " | ".join(e.text for e in resume.education if e.text))

    if resume.projects:
        bits = []
        for project in resume.projects[:3]:
            if not project.name:
                continue
            first = project.highlights[0] if project.highlights else ""
            bits.append(f"{project.name} - {first}" if first else project.name)
        if bits:
            parts.append("Projects: " + " | ".join(bits))

    return "\n".join(parts)


def summarize_job(job: Job) -> str:
    parts = [f"Title: {job.title}", f"Company: {job.company}", f"Location: {job.location}"]
    if job.level:
        parts.append(f"Level: {job.level}")
    if job.description:
        # Long postings push the resume out of a small model's context window;
        # the first ~4000 characters carry the role and requirements.
        parts.append("Description: " + job.description[:4000])
    return "\n".join(parts)


def build_messages(
    resume: ParsedResume,
    job: Job,
    *,
    tone: Tone = "professional",
    length: Length = "medium",
    matched_skills: list[str] | None = None,
    missing_skills: list[str] | None = None,
    hiring_manager: str | None = None,
) -> list[ChatMessage]:
    tone_text = TONE_GUIDANCE.get(tone, TONE_GUIDANCE["professional"])
    length_text = LENGTH_GUIDANCE.get(length, LENGTH_GUIDANCE["medium"])

    system = (
        "You are an expert cover letter writer for technical and quantitative roles. "
        "You write letters grounded in the candidate's actual background that read as "
        "though a person wrote them, not as a restatement of the resume.\n\n"
        f"TONE: {tone_text}\n"
        f"LENGTH: {length_text}\n\n"
        f"RULES:\n{_RULES}\n"
    )

    user_parts = [
        f"Write a cover letter for this role.\n\nJOB POSTING:\n{summarize_job(job)}",
        f"CANDIDATE BACKGROUND:\n{summarize_resume(resume)}",
    ]
    if matched_skills:
        user_parts.append(
            "The candidate demonstrably has these skills that the posting asks for — lead "
            "with the most relevant of them: " + ", ".join(matched_skills[:10])
        )
    if missing_skills:
        user_parts.append(
            "The posting also asks for these, which the resume does not evidence. Do NOT "
            "claim them. You may acknowledge adjacent experience if the resume supports it: "
            + ", ".join(missing_skills[:6])
        )
    if hiring_manager:
        user_parts.append(f"Address the letter to {hiring_manager}.")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
