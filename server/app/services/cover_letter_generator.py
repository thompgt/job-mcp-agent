# server/app/services/cover_letter_generator.py

from __future__ import annotations
from typing import Dict, Any, Optional

# LangChain + Ollama
try:
    from langchain_community.chat_models import ChatOllama
    from langchain_core.messages import SystemMessage, HumanMessage
except Exception as e:
    # Catch ALL exceptions, not just ImportError
    import logging
    logging.warning(f"Failed to import ChatOllama: {type(e).__name__}: {e}")
    ChatOllama = None
    SystemMessage = HumanMessage = None


def _format_resume_for_prompt(resume: Dict[str, Any]) -> str:
    """
    Turn the parsed resume dict (output of parse_resume_file) into a concise
    summary for the LLM prompt.

    Important design choices:
    - We intentionally ignore long free-text "profile"/"summary"/"objective"
      sections, since they are often generic and can make the model copy
      low-value fluff.
    - We compress experiences into short, information-dense snippets instead
      of dumping raw bullet points. This encourages the model to paraphrase
      and organize the information rather than mirror resume structure.
    """
    parts: list[str] = []

    # Candidate name (for context only, not for the model to restate literally)
    if resume.get("name"):
        parts.append(f"Candidate: {resume['name']}")

    # Ignore raw profile/summary paragraphs here on purpose; if present in the
    # parsed resume under keys like 'profile' or 'summary', we skip them.
    # If in future we want to mine keywords, we can add a light keyword
    # extraction step instead of copying the full text.
    # profile_text = resume.get("profile") or resume.get("summary") or resume.get("objective")

    # Contacts (useful for the model to infer professionalism and online presence,
    # but not something to copy verbatim)
    contacts = resume.get("contacts", {})
    contact_bits: list[str] = []
    if contacts.get("email"):
        contact_bits.append(f"email: {contacts['email']}")
    if contacts.get("linkedin"):
        contact_bits.append(f"linkedin: {contacts['linkedin']}")
    if contacts.get("github"):
        contact_bits.append(f"github: {contacts['github']}")
    if contact_bits:
        parts.append("Contacts: " + ", ".join(contact_bits))

    # Skills (keep a compact, sorted list, truncated if very long)
    skills = resume.get("skills") or []
    if skills:
        max_skills = 20
        trimmed = sorted(skills)[:max_skills]
        if len(skills) > max_skills:
            trimmed.append("...")
        parts.append("Skills: " + ", ".join(trimmed))

    # Experience: turn each role into a short narrative snippet instead of raw bullets
    experience = resume.get("experience") or []
    exp_snippets: list[str] = []
    for role in experience[:5]:  # cap number of roles for prompt brevity
        if not isinstance(role, dict):
            continue
        org = (role.get("organization") or "").strip()
        title = (role.get("title") or "").strip()
        period = (role.get("period") or "").strip()
        highlights = role.get("highlights") or []

        # Build a compact header
        header_bits = [b for b in [title, org] if b]
        header = " at ".join(header_bits)
        if period:
            header = f"{header} ({period})" if header else period

        # Take up to 2 highlights and join them into a single descriptive phrase
        hl_text = " ".join(h.strip() for h in highlights[:2] if isinstance(h, str))
        if header and hl_text:
            snippet = f"{header}: {hl_text}"
        elif header:
            snippet = header
        elif hl_text:
            snippet = hl_text
        else:
            snippet = ""

        snippet = snippet.strip()
        if snippet:
            exp_snippets.append(snippet)

    if exp_snippets:
        parts.append("Experience (condensed):")
        for s in exp_snippets:
            parts.append(f"- {s}")

    # Education: join entries into a single line
    education = resume.get("education") or []
    edu_bits: list[str] = []
    for ed in education:
        if isinstance(ed, dict):
            txt = (ed.get("text") or "").strip()
        else:
            txt = str(ed).strip()
        if txt:
            edu_bits.append(txt)
    if edu_bits:
        parts.append("Education: " + " | ".join(edu_bits))

    # Projects: only the strongest 2–3, short snippets
    projects = resume.get("projects") or []
    proj_bits: list[str] = []
    for proj in projects[:3]:
        if isinstance(proj, dict):
            name = (proj.get("name") or "").strip()
            highlights = proj.get("highlights") or []
            hl = " ".join(h.strip() for h in highlights[:1] if isinstance(h, str))
        else:
            name = str(proj).strip()
            hl = ""
        if name:
            snippet = name
            if hl:
                snippet += f" – {hl}"
            proj_bits.append(snippet)
    if proj_bits:
        parts.append("Projects: " + " | ".join(proj_bits))

    return "\n".join(parts)


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
    model_name: str = "llama3.2:1b",
    temperature: float = 0.7,
    tone: str = "professional",
    length: str = "medium",
) -> str:
    """
    Generate a personalized cover letter using a local Ollama model via LangChain.
    If Ollama isn't available, fall back to a templated letter.

    resume: dict from parse_resume_file(...)
    job: dict from your job source / queue
    tone: "professional", "enthusiastic", "concise", or "academic"
    length: "short", "medium", or "long"
    """

    resume_str = _format_resume_for_prompt(resume)
    job_str = _format_job_for_prompt(job)

    # Tone-specific instructions
    tone_instructions = {
        "professional": "Maintain a standard, respectful, and balanced professional tone.",
        "enthusiastic": "Use a highly passionate and energetic tone, showing extreme excitement for the company and role.",
        "concise": "Be very direct and to the point. Avoid fluff and keep every sentence high-impact.",
        "academic": "Use a formal academic tone, emphasizing research, education, and theoretical foundations."
    }.get(tone, "Maintain a professional tone.")

    # Length-specific instructions
    length_instructions = {
        "short": "Write a short cover letter (1-2 paragraphs, max 200 words).",
        "medium": "Write a standard length cover letter (3-4 paragraphs, around 400 words).",
        "long": "Write a detailed cover letter (4-5 paragraphs, around 600 words)."
    }.get(length, "Write a standard length cover letter.")

    # --- Upgraded System Prompt ---
    system_prompt = (
        "You are an expert cover letter writer for technical and quantitative roles. "
        "Your job is to write a professional, human-sounding cover letter that is based "
        "on the candidate's resume and the job description, but NOT a literal restatement "
        "of the resume.\n\n"
        f"TONE AND STYLE: {tone_instructions}\n"
        f"LENGTH: {length_instructions}\n\n"
        "Key requirements:\n"
        "1. Identify 2–3 core themes in the candidate's background (e.g., research ability, "
        "   engineering rigor, quantitative analysis, collaboration, ownership).\n"
        "2. Merge related experiences into coherent paragraphs instead of listing each job "
        "   separately.\n"
        "3. Paraphrase and summarize resume details; do NOT copy bullet points or phrases verbatim.\n"
        "4. Add small, realistic elaborations (e.g., how skills were applied, impact, what was learned) "
        "   without inventing new factual achievements.\n"
        "5. Use strong transitions and narrative flow; avoid repetitive sentence openings like "
        "   'As a ...' for each role.\n"
        "6. Integrate only the most relevant skills, rather than dumping the full skill list.\n"
        f"7. {length_instructions}\n"
        "8. If no hiring manager name is provided, begin with a greeting like "
        "   'Dear [Company] Recruitment Team,' or 'Dear Hiring Manager,'.\n"
        "9. Do not include the candidate's email, phone, or LinkedIn inside the letter body.\n"
        "10. Do not start with 'My name is ...'; instead, jump directly into motivation and fit.\n"
        "11. From the job description, explicitly extract 2–3 concrete details about the company, team, "
        "    mission, product, or tech stack (only if they are actually stated) and weave them naturally "
        "    into the letter.\n"
        "12. Use these details to write one focused paragraph explaining why the candidate is specifically "
        "    excited about this company and this role, not just generic enthusiasm.\n"
        "13. Never invent company facts that are not clearly implied or stated in the job description; "
        "    if the description is generic, keep the company-fit paragraph appropriately general.\n"
    )

    # --- Upgraded Human Prompt ---
    human_prompt = (
        f"Write a tailored cover letter with a {tone} tone and {length} length for the following role using the candidate's background.\n\n"
        "Do NOT copy the resume directly. Instead, paraphrase and generalize the experience "
        "into smooth narrative paragraphs. Focus on how the candidate's experience and skills "
        "make them a strong fit for THIS specific job.\n\n"
        "JOB DESCRIPTION:\n"
        f"{job_str}\n\n"
        "CANDIDATE RESUME (CONDENSED):\n"
        f"{resume_str}\n\n"
        "Instructions:\n"
        "- Emphasize relevant experience, projects, and skills for this job.\n"
        "- Connect past work to the responsibilities and tech stack of the role.\n"
        f"- {tone_instructions}\n"
        "- End with a short, clear call to action about next steps (e.g., willingness to interview).\n"
    )

    # Try Ollama
    if ChatOllama is not None:
        try:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Generating cover letter with Ollama model: {model_name}")
            
            llm = ChatOllama(
                model=model_name,
                temperature=temperature,
            )

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_prompt),
            ]

            logger.info("Invoking Ollama for cover letter generation...")
            response = llm.invoke(messages)

            if hasattr(response, "content"):
                letter = response.content.strip()
                logger.info(f"Cover letter generated successfully via Ollama ({len(letter)} chars)")
                return letter
            else:
                raise RuntimeError("Ollama response has no content")

        except Exception as e:
            # NO FALLBACK - Raise the error so user knows what went wrong
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Ollama generation FAILED: {e}")
            raise RuntimeError(
                f"Cover letter generation failed. Ollama error: {str(e)}. "
                f"Make sure Ollama is running (ollama serve) and model '{model_name}' is installed (ollama pull {model_name})"
            ) from e
    else:
        # ChatOllama not available - fail immediately
        raise RuntimeError(
            "ChatOllama is not available. Install it with: pip install langchain-community"
        )
