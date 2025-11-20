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
    Convert the parsed résumé into a clean, structured summary that avoids
    broken bullet formatting and gives the LLM predictable fields.
    """
    lines = []

    # Candidate name
    if resume.get("name"):
        lines.append(f"Name: {resume['name']}")

    # Contacts
    contacts = resume.get("contacts", {})
    if contacts:
        contact_str = ", ".join(
            f"{k}: {v}" for k, v in contacts.items() if v
        )
        lines.append(f"Contacts: {contact_str}")

    # Skills
    skills = resume.get("skills")
    if skills:
        lines.append("Skills: " + ", ".join(sorted(skills)))

    # Experience (clean structured blocks)
    experiences = resume.get("experience", [])
    if experiences:
        lines.append("Experience:")
        for exp in experiences:
            org = exp.get("organization", "")
            title = exp.get("title", "")
            period = exp.get("period", "")
            highlights = exp.get("highlights", [])

            lines.append("  - Role:")
            if title:
                lines.append(f"      Title: {title}")
            if org:
                lines.append(f"      Organization: {org}")
            if period:
                lines.append(f"      Period: {period}")

            if highlights:
                lines.append("      Responsibilities:")
                for h in highlights[:3]:
                    lines.append(f"        • {h}")

    # Education
    education = resume.get("education", [])
    if education:
        lines.append("Education:")
        for ed in education:
            txt = ed.get("text", "")
            if txt:
                lines.append(f"  - {txt}")

    # Projects
    projects = resume.get("projects", [])
    if projects:
        lines.append("Projects:")
        for p in projects[:3]:
            name = p.get("name", "")
            lines.append(f"  - {name}")
            for h in p.get("highlights", [])[:2]:
                lines.append(f"      • {h}")

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


def _summarize_experiences_as_sentences(experiences: list[dict[str, Any]]) -> list[str]:
    """
    Take structured experience blocks and turn each into a short readable paragraph.

    Example output element:
    "As a Quantitative Algorithm Developer Intern at RBC Capital Markets (2025 – Aug 2025),
     I built XYZ, collaborated with ABC, and delivered DEF."
    """
    out: list[str] = []

    for role in experiences:
        org = role.get("organization", "")  # e.g. "Royal Bank of Canada Capital Markets, New York, NY"
        title = role.get("title", "")        # e.g. "Quantitative Algorithm Developer Intern"
        period = role.get("period", "")      # e.g. "2025 – Aug 2025"
        highlights = role.get("highlights", []) or []

        # Clean up org if it's like "Org, Location" and title already has org etc.
        # (We won't over-engineer that now; just present it naturally.)

        # Join first 2-3 highlights into one flowing sentence-ish block.
        # We'll trim trailing periods to avoid "...,." issues.
        cleaned_points = []
        for h in highlights[:3]:
            h_clean = h.strip()
            # remove trailing period because we'll stitch them with commas
            if h_clean.endswith("."):
                h_clean = h_clean[:-1]
            cleaned_points.append(h_clean)

        # Build the "actions/results" chunk like:
        # "I developed X, worked on Y, and improved Z."
        action_chunk = ""
        if len(cleaned_points) == 1:
            action_chunk = f"I {cleaned_points[0]}."
        elif len(cleaned_points) == 2:
            action_chunk = f"I {cleaned_points[0]}, and I {cleaned_points[1]}."
        elif len(cleaned_points) >= 3:
            action_chunk = f"I {cleaned_points[0]}, {cleaned_points[1]}, and {cleaned_points[2]}."
        else:
            action_chunk = ""

        # Build header like:
        # "As a Quantitative Algorithm Developer Intern at Royal Bank of Canada Capital Markets (2025 – Aug 2025), ..."
        header_bits = []
        if title:
            header_bits.append(f"As a {title}")
        if org:
            header_bits.append(f"at {org}")
        if period:
            header_bits.append(f"({period})")
        header_text = " ".join(header_bits).strip()

        if header_text and action_chunk:
            paragraph = f"{header_text}, {action_chunk}"
        elif header_text:
            paragraph = header_text + "."
        else:
            # fallback if we somehow have no structured header
            paragraph = action_chunk if action_chunk else ""

        if paragraph:
            out.append(paragraph)

    return out


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
        "You are an industry expert, with an extremely high IQ of 167, and a helpful assistant that writes professional and personalized "
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

    # experience paragraph(s) in natural language using highlights
    experiences = resume.get("experience", [])
    if experiences:
        exp_summaries = _summarize_experiences_as_sentences(experiences[:3])
        if exp_summaries:
            paragraphs.append(
                "In my recent roles, I have built a strong foundation in quantitative analysis, research, and data-driven problem solving:"
            )
            for para in exp_summaries:
                paragraphs.append(para)

    # close
    paragraphs.append(
        "I would welcome the opportunity to discuss how my skills and experience can support your goals. "
        "Thank you for your time and consideration, and I look forward to the possibility of contributing to your team."
    )

    return "\n\n".join(paragraphs)


if __name__ == "__main__":
    """Simple CLI to test cover letter generation.

    Usage examples (run from project root):
      python -m server.app.services.cover_letter_generator --demo
      python -m server.app.services.cover_letter_generator --resume-json resume.json --job-json job.json
    """
    import argparse
    import json
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Test cover letter generator")
    ap.add_argument("--demo", action="store_true", help="use built-in demo resume and job")
    ap.add_argument("--resume-json", type=str, help="path to parsed resume JSON file")
    ap.add_argument("--job-json", type=str, help="path to job posting JSON file")
    args = ap.parse_args()

    resume = None
    job = None

    if args.demo:
        resume = {
            "name": "Alex Example",
            "contacts": {"email": "alex@example.com", "phone": "+1 555 123 4567"},
            "skills": ["python", "sql", "aws", "docker"],
            "experience": [
                {
                    "organization": "ExampleCorp, Remote",
                    "title": "Software Engineer",
                    "period": "2022 - Present",
                    "highlights": [
                        "Implemented ETL pipelines that processed 10M+ records/day",
                        "Reduced query latency by 40% through indexing and query tuning",
                    ],
                }
            ],
            "education": [{"text": "B.Sc. Computer Science, University X (2020)"}],
            "projects": [{"name": "Smart ETL", "highlights": ["Built end-to-end ETL"]}],
        }

        job = {
            "title": "Backend Engineer",
            "companyName": "Acme Analytics",
            "location": "Remote",
            "description": "Work on data pipelines, scalable backend services, and CI/CD.",
        }

    if args.resume_json:
        p = Path(args.resume_json)
        if not p.exists():
            print("resume json not found:", args.resume_json)
            raise SystemExit(2)
        with p.open("r", encoding="utf-8") as fh:
            resume = json.load(fh)

    if args.job_json:
        p = Path(args.job_json)
        if not p.exists():
            print("job json not found:", args.job_json)
            raise SystemExit(2)
        with p.open("r", encoding="utf-8") as fh:
            job = json.load(fh)

    if resume is None or job is None:
        print("Either --demo or both --resume-json and --job-json are required")
        raise SystemExit(2)

    out = generate_cover_letter(resume, job)
    print("\n--- Generated cover letter ---\n")
    print(out)

