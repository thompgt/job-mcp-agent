from __future__ import annotations
from typing import Dict, Any

# LangChain + Ollama
try:
    from langchain_community.chat_models import ChatOllama
    from langchain.schema import SystemMessage, HumanMessage
except ImportError:
    ChatOllama = None
    SystemMessage = HumanMessage = None


def _format_resume_for_prompt(resume: Dict[str, Any]) -> str:
    """
    Turn the parsed resume dict (output of parse_resume_file) into a concise,
    human-readable summary for the LLM prompt.
    """
    lines: list[str] = []

    # Candidate name
    if resume.get("name"):
        lines.append(f"Candidate Name: {resume['name']}")

    # Contact info
    contacts = resume.get("contacts", {})
    contact_bits = []
    if contacts.get("email"):
        contact_bits.append(f"email: {contacts['email']}")
    if contacts.get("linkedin"):
        contact_bits.append(f"linkedin: {contacts['linkedin']}")
    if contacts.get("github"):
        contact_bits.append(f"github: {contacts['github']}")
    if contact_bits:
        lines.append("Contacts: " + ", ".join(contact_bits))

    # Skills
    skills = resume.get("skills")
    if skills:
        lines.append("Skills: " + ", ".join(sorted(skills)))

    # Experience (list of dicts with organization/title/period/highlights)
    experience = resume.get("experience")
    if experience:
        lines.append("Experience:")
        for role in experience:
            org = role.get("organization", "")
            title = role.get("title", "")
            period = role.get("period", "")
            header = " | ".join(x for x in [org, title, period] if x)
            if header:
                lines.append(f"- {header}")
            # include first couple bullet points to keep prompt small
            for h in role.get("highlights", [])[:2]:
                lines.append(f"    • {h}")

    # Education
    education = resume.get("education")
    if education:
        edu_bits = []
        for ed in education:
            txt = ed.get("text", "")
            if txt:
                edu_bits.append(txt.strip())
        if edu_bits:
            lines.append("Education: " + " | ".join(edu_bits))

    # Projects
    projects = resume.get("projects")
    if projects:
        lines.append("Projects:")
        for proj in projects[:3]:  # don't explode prompt
            name = proj.get("name")
            if name:
                lines.append(f"- {name}")
            for h in proj.get("highlights", [])[:2]:
                lines.append(f"    • {h}")

    return "\n".join(lines)


def _format_job_for_prompt(job: Dict[str, Any]) -> str:
    """
    Turn a job posting dict into human-readable text for the prompt.
    Handles different possible field names since job sources vary.
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


def generate_cover_letter(
    resume: Dict[str, Any],
    job: Dict[str, Any],
    *,
    model_name: str = "llama3.2",
    temperature: float = 0.7,
) -> str:
    """
    Generate a personalized cover letter using a local Ollama model via LangChain.
    If Ollama isn't available or errors, fall back to a deterministic template.

    resume: dict returned by parse_resume_file(...)
    job: dict from your job postings / queue
    """
    resume_str = _format_resume_for_prompt(resume)
    job_str = _format_job_for_prompt(job)

    system_prompt = (
        "You are a helpful assistant that writes professional and personalized "
        "cover letters. Your letters should be concise (3–4 paragraphs), "
        "highlight relevant skills and experiences from the candidate's résumé, "
        "and explain why the candidate is a strong fit for the job. "
        "If no hiring manager name is provided, start with something like "
        "'Dear Hiring Manager,' or 'Dear [Company] Recruitment Team,'."
    )

    human_prompt = (
        "Please craft a cover letter using the following job description and "
        "candidate résumé. You may infer connections between the job's required "
        "skills and the candidate's background. Use a confident but polite tone. "
        "End with a brief request to interview.\n\n"
        f"Job Details:\n{job_str}\n\n"
        f"Candidate Résumé:\n{resume_str}"
    )

    # Try local Ollama model first
    if ChatOllama is not None:
        try:
            llm = ChatOllama(
                model=model_name,
                temperature=temperature,
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]

            response = llm(messages)

            if hasattr(response, "content"):
                return response.content.strip()

        except Exception:
            # Fall through to fallback
            pass

    # -------- fallback path (no LLM or LLM error) --------

    job_title = (
        job.get("title")
        or job.get("jobTitle")
        or job.get("name")
        or "the position"
    )

    company_name = (
        job.get("companyName")
        or job.get("company")
        or job.get("org")
        or "the company"
    )

    greeting = f"Dear {company_name} Recruitment Team,"

    paragraphs: list[str] = []

    # intro
    paragraphs.append(
        f"{greeting}\n\n"
        f"I am writing to express my interest in the {job_title} role at {company_name}. "
        "With my background and skills, I believe I would be an immediate contributor to your team."
    )

    # skills paragraph
    if resume.get("skills"):
        skills_list = ", ".join(sorted(resume["skills"]))
        paragraphs.append(
            f"Throughout my academic and professional journey I have developed strengths in {skills_list}. "
            "These technical and analytical abilities align closely with the responsibilities outlined in the posting."
        )

    # experience paragraph with multiple roles
    if resume.get("experience"):
        experiences = resume["experience"]
        paragraphs.append(
            "Across my recent experiences, I have developed a strong foundation in data- and software-driven problem solving:"
        )
        for role in experiences[:3]:  # include up to 3 experiences for brevity
            org = role.get("organization", "")
            title = role.get("title", "")
            period = role.get("period", "")
            header = ", ".join(x for x in [title, org, period] if x)
            highlights = role.get("highlights", [])
            bullet_text = " ".join(highlights[:1]) if highlights else ""
            paragraphs.append(f"- {header}: {bullet_text}")

    # close
    paragraphs.append(
        "I would welcome the opportunity to discuss how my skills and experience can support your goals. "
        "Thank you for your time and consideration, and I look forward to the possibility of contributing to your team."
    )

    return "\n\n".join(paragraphs)
