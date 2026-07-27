"""Cover letter generation, with two fallbacks below the language model.

The order is deliberate:

1. **Ollama**, when it is running — prose, generated locally.
2. **A brief**, when it is not and the caller can use one. This is the
   interesting case for an MCP server: the host already *has* a capable model
   reading the tool result. Handing it grounded material (matched skills,
   concrete hooks pulled from the posting, a paragraph plan) produces a better
   letter than a local 1B model would, and it works on a machine with no
   Ollama at all.
3. **A template**, as a last resort, so the tool always returns something
   usable.

v1 had none of these. Its docstring promised a templated fallback, the code
raised ``RuntimeError`` instead, and the whole feature was unavailable to
anyone who had not installed Ollama and pulled a model.
"""

from __future__ import annotations

import re

from careercraft.core.letters.prompts import build_messages
from careercraft.core.resume.skills import skill_overlap
from careercraft.errors import CareerCraftError
from careercraft.llm import LLMProvider
from careercraft.logging import get_logger
from careercraft.models import (
    CoverLetter,
    Job,
    Length,
    LetterBrief,
    ParsedResume,
    Tone,
)

log = get_logger(__name__)

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_THEME_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("hands-on engineering delivery", ("engineer", "developer", "software", "backend", "platform")),
    ("data and quantitative analysis", ("data", "analyst", "quantitative", "research", "scientist")),
    ("machine learning practice", ("machine learning", "ml", "ai", "model", "nlp")),
    ("infrastructure and operations", ("devops", "cloud", "infrastructure", "sre", "platform")),
    ("leadership and ownership", ("lead", "president", "board", "founder", "captain", "manager")),
    ("teaching and communication", ("tutor", "teaching", "mentor", "instructor", "writing")),
]


def _themes(resume: ParsedResume, job: Job) -> list[str]:
    """Pick the two or three angles worth building the letter around."""
    haystack = " ".join(
        [
            " ".join(e.title for e in resume.experience),
            " ".join(h for e in resume.experience for h in e.highlights),
            " ".join(p.name for p in resume.projects),
            " ".join(resume.skills),
        ]
    ).lower()
    job_text = f"{job.title} {job.description}".lower()

    def mentions(hint: str, text: str) -> bool:
        # Word boundaries, not substrings: "ai" otherwise matches "Airflow"
        # and every resume acquires a machine-learning theme.
        return re.search(rf"\b{re.escape(hint)}\b", text) is not None

    scored = []
    for theme, hints in _THEME_HINTS:
        in_resume = sum(mentions(hint, haystack) for hint in hints)
        in_job = sum(mentions(hint, job_text) for hint in hints)
        if in_resume:
            scored.append((in_job * 2 + in_resume, theme))
    scored.sort(reverse=True)
    themes = [theme for _score, theme in scored[:3]]
    return themes or ["relevant technical experience"]


def _evidence(resume: ParsedResume, limit: int = 4) -> list[str]:
    """The concrete, checkable statements a letter should be built on."""
    out: list[str] = []
    for role in resume.experience:
        header = " at ".join(b for b in (role.title, role.organization) if b)
        if role.highlights:
            out.append(f"{header}: {role.highlights[0]}" if header else role.highlights[0])
        elif header:
            out.append(header)
    for project in resume.projects:
        if project.name and project.highlights:
            out.append(f"{project.name}: {project.highlights[0]}")
        elif project.name:
            out.append(project.name)
    return out[:limit]


def _company_hooks(job: Job, limit: int = 3) -> list[str]:
    """Sentences from the posting that say something specific about the company.

    Filtered to those that actually name a product, mission or stack, because
    a hook drawn from boilerplate ("we are an equal opportunity employer")
    makes a letter worse, not better.
    """
    if not job.description:
        return []
    signals = (
        "we build",
        "we are building",
        "our mission",
        "our platform",
        "our product",
        "our team",
        "you will",
        "you'll",
        "the role",
        "we use",
        "stack",
    )
    noise = ("equal opportunity", "regardless of race", "e-verify", "compensation range")
    hooks = []
    for sentence in _SENTENCE_RE.split(job.description):
        clean = sentence.strip()
        lowered = clean.lower()
        if 40 <= len(clean) <= 240 and any(s in lowered for s in signals):
            if not any(n in lowered for n in noise):
                hooks.append(clean)
    return hooks[:limit]


def build_brief(
    resume: ParsedResume,
    job: Job,
    *,
    tone: Tone = "professional",
    length: Length = "medium",
) -> LetterBrief:
    """Assemble everything a writer needs, without writing anything."""
    matched, missing = skill_overlap(resume.skills, job.to_search_text())
    themes = _themes(resume, job)
    company = job.company or "the company"

    plan = [
        f"Opening: why this role at {company} specifically — name a concrete detail from "
        "the posting, not generic enthusiasm.",
        f"Body 1: {themes[0]}, evidenced by the strongest matching experience.",
    ]
    if len(themes) > 1:
        plan.append(f"Body 2: {themes[1]}, tied to what the posting asks for.")
    if length == "long" and len(themes) > 2:
        plan.append(f"Body 3: {themes[2]}.")
    plan.append("Close: a short, concrete call to action about next steps.")

    return LetterBrief(
        company=company,
        role=job.title,
        opening_hook=(
            f"Connect the candidate's {themes[0]} to {company}'s "
            f"{job.title.lower()} role."
        ),
        themes=themes,
        evidence=_evidence(resume),
        company_hooks=_company_hooks(job),
        closing=(
            "Reiterate fit in one sentence and ask for a conversation. "
            f"Tone: {tone}."
        ),
        paragraph_plan=plan,
    )


def render_template(
    resume: ParsedResume,
    job: Job,
    *,
    tone: Tone = "professional",
    length: Length = "medium",
) -> str:
    """A serviceable letter with no model involved.

    Honest about what it is: assembled from the candidate's own material, so
    every claim in it is one the resume supports.
    """
    brief = build_brief(resume, job, tone=tone, length=length)
    matched, _missing = skill_overlap(resume.skills, job.to_search_text())
    company = job.company or "your team"
    name = resume.name or ""

    opening = (
        f"Dear Hiring Manager,\n\n"
        f"I am writing to apply for the {job.title} position at {company}. "
        f"My background in {brief.themes[0]} lines up closely with what the role calls for."
    )

    if matched:
        skills_line = (
            f" In particular, I work regularly with {', '.join(matched[:6])}, "
            "which the posting highlights."
        )
    else:
        skills_line = (
            f" I bring hands-on experience with {', '.join(resume.skills[:6])}."
            if resume.skills
            else ""
        )

    body_bits = []
    for item in brief.evidence[: 2 if length == "short" else 4]:
        body_bits.append(item.rstrip(".") + ".")
    body = " ".join(body_bits) if body_bits else ""

    hook = ""
    if brief.company_hooks:
        hook = (
            f"\n\nWhat draws me to {company} in particular: {brief.company_hooks[0].rstrip('.')}. "
            "That is the kind of work I want to be doing."
        )

    closing = (
        f"\n\nI would welcome the chance to discuss how I could contribute to {company}. "
        "Thank you for your time and consideration.\n\nSincerely,\n" + (name or "")
    ).rstrip()

    middle = f"\n\n{skills_line.strip()} {body}".rstrip() if (skills_line or body) else ""
    return f"{opening}{middle}{hook}{closing}"


async def generate_letter(
    resume: ParsedResume,
    job: Job,
    *,
    provider: LLMProvider,
    tone: Tone = "professional",
    length: Length = "medium",
    model: str | None = None,
    temperature: float = 0.7,
    allow_brief: bool = True,
) -> CoverLetter:
    """Draft a letter, degrading gracefully when no model is reachable.

    ``allow_brief=False`` forces the template path instead of the brief, for
    callers that need finished prose no matter what — a web UI, say, where
    there is no downstream model to hand the brief to.
    """
    matched, missing = skill_overlap(resume.skills, job.to_search_text())
    base = {
        "job_id": job.id,
        "resume_id": resume.id or None,
        "tone": tone,
        "length": length,
    }

    if await provider.is_available():
        messages = build_messages(
            resume,
            job,
            tone=tone,
            length=length,
            matched_skills=matched,
            missing_skills=missing,
        )
        # is_available() is a cheap probe, not a promise. A daemon can be up
        # and still fail the request — the model was evicted, the context
        # overflowed, generation timed out. Falling through to the brief is
        # strictly better than handing the caller an exception, and the caller
        # can see which path ran from ``generated_by``.
        try:
            text = await provider.complete(messages, model=model, temperature=temperature)
        except (CareerCraftError, OSError) as exc:
            log.warning("letter.provider_failed", provider=provider.name, error=str(exc))
            text = ""
        if text.strip():
            return CoverLetter(
                **base,
                text=text,
                generated_by="ollama",
                model=model,
                word_count=len(text.split()),
            )
        log.warning("letter.empty_response", provider=provider.name)

    if allow_brief:
        return CoverLetter(
            **base,
            brief=build_brief(resume, job, tone=tone, length=length),
            generated_by="brief",
        )

    text = render_template(resume, job, tone=tone, length=length)
    return CoverLetter(**base, text=text, generated_by="template", word_count=len(text.split()))
