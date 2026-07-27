"""Structured parsing of resume text.

The heuristics here are ported from v1's ``resume_parser.py`` with their
behaviour intact — they were tuned against real documents and rewriting them
from scratch would trade known-good output for guesswork. What changed is the
plumbing: spaCy is now optional (it only sharpens name detection), layout
hints arrive as data instead of a file path, and the result is a typed model
instead of a free-form dict.
"""

from __future__ import annotations

import difflib
import re
from importlib.util import find_spec
from typing import Any

from careercraft.core.resume.extract import LayoutLine, normalize_text
from careercraft.core.resume.skills import extract_skills
from careercraft.models import (
    Contacts,
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
    ProjectEntry,
)

# ------------------------------------------------------------------ regexes

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-]*)?(?:\(?\d{2,4}\)?[\s\-]*){2,4}\d{2,4}")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/[A-Za-z0-9_/\-]+", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_\-/.]+", re.I)

DEGREE_RE = re.compile(
    r"\b(B\.?Sc|B\.?S|M\.?Sc|M\.?S|B\.?Eng|M\.?Eng|Ph\.?D|Bachelor|Master|Doctor|BA|MA)\b",
    re.I,
)
YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_YEAR = r"(?:19|20)\d{2}"
_SEP = r"\s*[—\-–]\s*"
DATE_RANGE_RE = re.compile(
    rf"(?:{_MONTH}\s+\d{{4}}|{_YEAR}){_SEP}(?:{_MONTH}\s+\d{{4}}|{_YEAR}|Present)",
    re.I,
)

SECTION_RE = re.compile(
    r"""(?im)^\s*(
        profile|summary|objective|
        contact|contacts|
        education|
        work\s+experience|professional\s+experience|experience|
        internship\s+experience|
        leadership\s*&\s*projects|additional\s+projects|academic\s+projects|projects|
        skills|technical\s+skills|
        certifications|
        awards|honors|
        extra[-\s]?curricular
    )\s*[:\-]?\s*$""",
    re.X,
)

CANONICAL_SECTIONS: dict[str, list[str]] = {
    "profile": ["profile", "summary", "about me", "objective"],
    "contact": ["contact", "contacts", "contact details"],
    "skills": ["skills", "technical skills", "key skills", "core competencies"],
    "education": ["education", "academics", "academic background"],
    # Keys here are the canonical vocabulary that ends up in
    # ``ParsedResume.sections_detected``, which is part of the MCP contract —
    # so both header detectors must agree on them. Shortest natural form wins;
    # the longer spellings are aliases.
    "experience": [
        "experience",
        "work experience",
        "professional experience",
        "employment",
    ],
    "internship experience": ["internship experience", "internships", "internship"],
    "projects": ["projects", "academic projects", "course projects", "additional projects"],
    "certifications": ["certifications", "certificates", "licenses"],
    "extra-curricular": [
        "extra-curricular activities",
        "extracurricular",
        "activities",
        "volunteering",
    ],
    "awards": ["awards", "honors", "achievements"],
}
ALL_HEADER_VARIANTS = {
    alias: key for key, aliases in CANONICAL_SECTIONS.items() for alias in [key, *aliases]
}

NAME_BLACKLIST = {
    "education",
    "experience",
    "work experience",
    "skills",
    "projects",
    "profile",
    "contact",
    "contacts",
    "summary",
    "curriculum vitae",
    "resume",
}

BULLET_HEAD = re.compile(r"^[•\-\*•]\s*")
MONTH_WORD = re.compile(rf"^{_MONTH}$", re.I)

EXPERIENCE_SECTIONS = ("experience", "internship experience")
PROJECT_SECTIONS = ("projects",)


# ------------------------------------------------------------ contact / name


def _norm_url(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith(("http://", "https://")) else "https://" + url


def _extract_contacts(text: str) -> Contacts:
    def first(rx: re.Pattern[str]) -> str | None:
        match = rx.search(text)
        return match.group(0) if match else None

    return Contacts(
        email=first(EMAIL_RE),
        phone=first(PHONE_RE),
        linkedin=_norm_url(first(LINKEDIN_RE)),
        github=_norm_url(first(GITHUB_RE)),
    )


def _looks_like_name(line: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z\s\-']", " ", line).strip()
    if not cleaned:
        return False
    words = cleaned.split()
    if not 1 <= len(words) <= 4:
        return False
    if cleaned.lower() in NAME_BLACKLIST:
        return False
    return all(2 <= len(w) <= 20 and re.fullmatch(r"[A-Za-z\-']+", w) for w in words)


def _spacy_person(text: str, model: str) -> str | None:
    """Ask spaCy for a PERSON entity. Optional, and never fatal.

    This is the *only* thing spaCy is used for now. When it is absent, a name
    that is not on one of the first lines simply goes undetected, which the
    caller can see from ``ParsedResume.backend``.
    """
    try:
        if find_spec("spacy") is None:
            return None
    except (ImportError, ValueError):
        return None
    try:
        nlp = _load_spacy(model)
    except Exception:
        return None
    doc = nlp(text[:5000])
    for ent in doc.ents:
        if ent.label_ == "PERSON" and ent.text.lower() not in NAME_BLACKLIST:
            return str(ent.text).strip()
    return None


_SPACY_CACHE: dict[str, object] = {}


def _load_spacy(model: str) -> Any:
    if model not in _SPACY_CACHE:
        import spacy

        _SPACY_CACHE[model] = spacy.load(model, disable=["lemmatizer", "textcat"])
    return _SPACY_CACHE[model]


def _extract_name(text: str, *, spacy_model: str | None) -> tuple[str | None, bool]:
    """Return ``(name, used_spacy)``."""
    for line in [ln.strip() for ln in text.splitlines()[:6] if ln.strip()]:
        if _looks_like_name(line):
            return (line.title() if line.isupper() else line), False
    if spacy_model:
        person = _spacy_person(text, spacy_model)
        if person:
            return person, True
    return None, False


# --------------------------------------------------------- section splitting


def _looks_like_header(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and bool(re.fullmatch(r"[A-Z0-9 &/\-]{4,}", stripped))


def _normalize_header_name(name: str) -> str | None:
    lowered = name.lower()
    rules = [
        ("education", "education"),
        ("certif", "certifications"),
    ]
    if "intern" in lowered and "experience" in lowered:
        return "internship experience"
    if "experience" in lowered or "employment" in lowered:
        return "experience"
    if "project" in lowered:
        return "projects"
    if "extra" in lowered and "curricular" in lowered:
        return "extra-curricular"
    for needle, canonical in [
        *rules,
        ("profile", "profile"),
        ("contact", "contact"),
        ("skill", "skills"),
    ]:
        if needle in lowered:
            return canonical
    return None


def _normalize_header_freeform(name: str) -> str | None:
    """Fuzzy-match a visually-detected header to a canonical section name."""
    squashed = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 &/\-]", " ", name).strip().lower())
    if squashed in ALL_HEADER_VARIANTS:
        return ALL_HEADER_VARIANTS[squashed]
    best_key, best_sim = None, 0.0
    for key, aliases in CANONICAL_SECTIONS.items():
        sim = max(difflib.SequenceMatcher(None, squashed, x).ratio() for x in [key, *aliases])
        if sim > best_sim:
            best_key, best_sim = key, sim
    return best_key if best_sim >= 0.65 else None


def split_sections(text: str) -> dict[str, str]:
    """Split on explicit textual headers (``EDUCATION``, ``Experience:``).

    Each mark records where the header *begins* as well as where its body
    begins, because a section ends at the next header's first character, not
    at its last: closing on the wrong end leaves the literal text
    ``TECHNICAL SKILLS`` glued to the tail of the experience section, where it
    goes on to be parsed as an employer.
    """
    lines = text.splitlines(keepends=True)
    full = "".join(lines)

    # (name, header_start, body_start)
    marks: list[tuple[str, int, int]] = []
    for m in SECTION_RE.finditer(full):
        raw = m.group(1).lower()
        marks.append((_normalize_header_name(raw) or raw, m.start(), m.end()))

    offset = 0
    for line in lines:
        if _looks_like_header(line.rstrip("\n")):
            stripped = line.strip()
            canonical = _normalize_header_name(stripped) or _normalize_header_freeform(stripped)
            if canonical:
                marks.append((canonical, offset, offset + len(line)))
        offset += len(line)

    # The same header is often found twice — once by SECTION_RE and once by the
    # all-caps scan — with slightly different spans. Keep one mark per starting
    # position, preferring the one whose body starts latest so no part of the
    # header line survives into the body.
    by_start: dict[int, tuple[str, int, int]] = {}
    for mark in marks:
        existing = by_start.get(mark[1])
        if existing is None or mark[2] > existing[2]:
            by_start[mark[1]] = mark
    marks = sorted(by_start.values(), key=lambda m: m[1])
    if not marks:
        return {"full": full}

    sections: dict[str, str] = {}
    for i, (name, _header_start, body_start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(full)
        if end <= body_start:
            continue
        chunk = full[body_start:end].strip("\n").rstrip()
        if chunk:
            sections[name] = chunk
    return sections


def split_sections_by_layout(lines: list[LayoutLine]) -> dict[str, str] | None:
    """Infer sections from font size and weight.

    Catches resumes whose headers are purely visual — larger or bold text with
    no punctuation and no all-caps — which the textual splitter cannot see.
    """
    if not lines:
        return None

    sizes = sorted(line.size for line in lines)
    median = sizes[len(sizes) // 2]
    big = median * 1.15
    header_words = re.compile(
        r"(experience|education|profile|project|skill|certif|intern|activit|award|summary)", re.I
    )

    headers: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        letters = [c for c in line.text if c.isalpha()]
        is_caps = len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.7
        is_short = len(line.text.split()) <= 6
        if (line.size >= big or line.bold) and (
            is_caps or is_short or header_words.search(line.text)
        ):
            canonical = _normalize_header_freeform(line.text)
            if canonical:
                headers.append((canonical, idx))

    deduped: list[tuple[str, int]] = []
    for name, idx in sorted(headers, key=lambda h: h[1]):
        if deduped and deduped[-1][0] == name and idx - deduped[-1][1] <= 2:
            continue
        deduped.append((name, idx))
    if not deduped:
        return None

    out: dict[str, str] = {}
    for i, (name, line_idx) in enumerate(deduped):
        end_idx = deduped[i + 1][1] if i + 1 < len(deduped) else len(lines)
        chunk = "\n".join(line.text for line in lines[line_idx + 1 : end_idx]).strip()
        if chunk:
            out[name] = f"{out[name]}\n\n{chunk}" if name in out else chunk
    return out or None


# --------------------------------------------------------------- extractors


def _extract_education(section: str) -> list[EducationEntry]:
    rows: list[EducationEntry] = []
    for line in section.splitlines():
        degree = DEGREE_RE.search(line)
        years = YEAR_RE.findall(line)
        if degree or years:
            rows.append(
                EducationEntry(
                    text=line.strip(),
                    degree=degree.group(0) if degree else None,
                    years=list(years[-2:]),
                )
            )
    return rows


_HEADER_NAMES = {
    *EXPERIENCE_SECTIONS,
    *PROJECT_SECTIONS,
    "leadership & projects",
    "education",
    "skills",
    "profile",
    "contact",
    "contacts",
    "extra-curricular",
}

_LOCATION_RE = re.compile(
    r"^(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s?(?:[A-Z]{2}|[A-Z][a-z]+)|Remote|Hybrid)$"
)
_ROLE_WORDS = re.compile(
    r"(engineer|scientist|tutor|manager|lead|leader|board|analyst|developer|research"
    r"|intern|specialist|consultant|associate|architect|designer)",
    re.I,
)


def _reflow(lines: list[str]) -> list[str]:
    """Rejoin PDF line-wrapping into sentence-like bullets."""
    ends = re.compile(r"[.;:)\]%]\s*$")
    out: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            merged = re.sub(r"\s{2,}", " ", re.sub(r"\s*\+\s*", " + ", " ".join(buf).strip()))
            out.append(merged)
            buf.clear()

    for line in lines:
        if buf and ends.search(buf[-1]):
            flush()
        buf.append(line.strip())
    flush()
    return [s for s in out if len(s) >= 3]


def _clean_title(title: str) -> str:
    stripped = title.strip(" -—–|,")
    return "" if MONTH_WORD.fullmatch(stripped) else stripped


def _extract_experience(section: str) -> list[ExperienceEntry]:
    """Build organization → title(+period) → highlights blocks.

    Real resumes order these three inconsistently, so this walks the lines
    with a small state machine rather than assuming a fixed layout.
    """
    lines = [BULLET_HEAD.sub("", ln).strip() for ln in section.splitlines() if ln.strip()]
    entries: list[ExperienceEntry] = []
    current: dict[str, Any] | None = None

    company_like = re.compile(r"^[A-Z][A-Za-z0-9@&×/.,\-–— ]{1,80}$")
    role_plus_date = re.compile(rf"^(.+?)\s+({DATE_RANGE_RE.pattern})$", re.I)
    date_only = re.compile(rf"^\s*({DATE_RANGE_RE.pattern})\s*$", re.I)

    def is_header_like(text: str) -> bool:
        return text.strip().lower() in _HEADER_NAMES or (
            _looks_like_header(text) and _normalize_header_name(text) is not None
        )

    def blank() -> dict[str, Any]:
        return {"organization": "", "title": "", "period": None, "buf": []}

    def flush() -> None:
        nonlocal current
        if current:
            highlights = _reflow([s for s in current["buf"] if s])
            org = str(current["organization"]).strip()
            title = str(current["title"]).strip()
            if org or title or highlights:
                entries.append(
                    ExperienceEntry(
                        organization=org,
                        title=title,
                        period=(str(current["period"]).strip() or None)
                        if current["period"]
                        else None,
                        highlights=highlights,
                    )
                )
        current = None

    i = 0
    while i < len(lines):
        line = lines[i]

        if is_header_like(line):
            i += 1
            continue

        # role → location → date, the most common three-line block
        if (
            _ROLE_WORDS.search(line)
            and not date_only.match(line)
            and i + 2 < len(lines)
            and _LOCATION_RE.match(lines[i + 1])
            and (role_plus_date.match(lines[i + 2]) or date_only.match(lines[i + 2]))
        ):
            flush()
            current = blank()
            current["organization"] = f"{line}, {lines[i + 1]}"
            combined = role_plus_date.match(lines[i + 2])
            if combined:
                current["title"] = _clean_title(combined.group(1))
                current["period"] = combined.group(2).strip()
            else:
                current["title"] = _clean_title(line)
                period_match = date_only.match(lines[i + 2])
                assert period_match is not None
                current["period"] = period_match.group(1).strip()
            i += 3
            continue

        combined = role_plus_date.match(line)
        if combined:
            current = current or blank()
            current["title"] = _clean_title(combined.group(1))
            current["period"] = combined.group(2).strip()
            i += 1
            continue

        solo_date = date_only.match(line)
        if solo_date:
            current = current or blank()
            if (
                not current["title"]
                and i > 0
                and _ROLE_WORDS.search(lines[i - 1])
                and not date_only.match(lines[i - 1])
            ):
                current["title"] = _clean_title(lines[i - 1])
            current["period"] = solo_date.group(1).strip()
            i += 1
            continue

        # A capitalised line is only an employer if it also reads like a name
        # rather than a sentence: v1 classified "Built data pipelines in
        # Python." as an organization because it starts with a capital.
        if (
            company_like.match(line)
            and not line.islower()
            and not line.endswith((".", "!", "?"))
            and len(line.split()) <= 7
            and not _VERB_START.match(line)
            and not role_plus_date.search(line)
            and not _ROLE_WORDS.search(line)
        ):
            flush()
            current = blank()
            current["organization"] = line
            if i + 1 < len(lines) and _LOCATION_RE.match(lines[i + 1]):
                current["organization"] = f"{line}, {lines[i + 1]}"
                i += 1
            i += 1
            continue

        if _ROLE_WORDS.search(line) and not date_only.match(line):
            if i + 1 < len(lines) and date_only.match(lines[i + 1]):
                current = current or blank()
                current["title"] = _clean_title(line)
                next_date = date_only.match(lines[i + 1])
                assert next_date is not None
                current["period"] = next_date.group(1).strip()
                i += 2
                continue
            if current and current["buf"]:
                flush()
            current = current or blank()
            if not current["title"]:
                current["title"] = _clean_title(line)
            else:
                current["buf"].append(line)
            i += 1
            continue

        if _LOCATION_RE.match(line):
            if current and not current["organization"]:
                current["organization"] = line
            i += 1
            continue

        current = current or blank()
        current["buf"].append(line)
        i += 1

    flush()
    return entries


_VERB_START = re.compile(
    r"^(Built|Designed|Orchestrated|Implemented|Provisioned|Containerized|Drafted|Prototyped"
    r"|Defined|Planned|Created|Developed|Improved|Set\s+up|Established|Led|Analyzed)\b",
    re.I,
)


def _extract_projects(section: str) -> list[ProjectEntry]:
    lines = [BULLET_HEAD.sub("", ln).strip() for ln in section.splitlines() if ln.strip()]
    if not lines:
        return []

    date_only = re.compile(rf"^\s*({DATE_RANGE_RE.pattern})\s*$", re.I)

    def is_block_header(text: str) -> bool:
        if date_only.match(text) or _LOCATION_RE.match(text) or _VERB_START.match(text):
            return False
        if " — " in text or " - " in text:
            return True
        return bool(text[:1].isupper() and not text.endswith(".") and len(text) <= 120)

    blocks: list[list[str]] = []
    for line in lines:
        if is_block_header(line) or not blocks:
            blocks.append([line])
        else:
            blocks[-1].append(line)

    projects: list[ProjectEntry] = []
    for block in blocks:
        header = block[0].strip()
        name, location = header, None
        if "," in header:
            tail = header.rsplit(",", 1)[1].strip()
            if _LOCATION_RE.match(tail):
                location = tail
                name = header.rsplit(",", 1)[0].strip()

        date_match = DATE_RANGE_RE.search(header) or (
            DATE_RANGE_RE.search(block[1]) if len(block) > 1 else None
        )
        role_match = _ROLE_WORDS.search(header)

        highlights = _reflow(
            [s for s in block[1:] if not date_only.match(s) and not _LOCATION_RE.match(s)]
        )
        if _VERB_START.match(name) and highlights:
            # The "name" is actually the first bullet; the block had no header.
            highlights.insert(0, name)
            name = "Project"

        if name or highlights:
            projects.append(
                ProjectEntry(
                    name=name,
                    role=role_match.group(0).title() if role_match else None,
                    location=location,
                    period=date_match.group(0) if date_match else None,
                    highlights=highlights,
                )
            )
    return projects


def _extract_leadership(section: str) -> list[ExperienceEntry]:
    """Treat leadership roles as experience — they are, for matching purposes."""
    lines = [BULLET_HEAD.sub("", ln).strip() for ln in section.splitlines() if ln.strip()]
    date_only = re.compile(rf"^\s*({DATE_RANGE_RE.pattern})\s*$", re.I)
    role_words = re.compile(r"(executive|president|board|chair|lead|leader|captain|founder)", re.I)

    entries: list[ExperienceEntry] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if current:
            highlights = _reflow([s for s in current["buf"] if s])
            org, title = str(current["organization"]).strip(), str(current["title"]).strip()
            if org or title or highlights:
                entries.append(
                    ExperienceEntry(
                        organization=org,
                        title=title,
                        period=str(current["period"]).strip() if current["period"] else None,
                        highlights=highlights,
                    )
                )
        current = None

    for i, line in enumerate(lines):
        if _looks_like_header(line):
            continue
        if role_words.search(line) and not date_only.match(line):
            flush()
            current = {
                "organization": "",
                "title": line.strip(" -—–|,"),
                "period": None,
                "buf": [],
            }
            continue
        solo = date_only.match(line)
        if solo:
            current = current or {"organization": "", "title": "", "period": None, "buf": []}
            current["period"] = solo.group(1).strip()
            continue
        if _LOCATION_RE.match(line):
            if current and not current["organization"]:
                current["organization"] = line
            continue
        current = current or {"organization": "", "title": "", "period": None, "buf": []}
        current["buf"].append(line)
        _ = i
    flush()
    return entries


# --------------------------------------------------------------- entrypoint


def parse_resume_text(
    text: str,
    *,
    layout_lines: list[LayoutLine] | None = None,
    spacy_model: str | None = None,
    extra_skill_terms: tuple[str, ...] = (),
    source_name: str | None = None,
    used_ocr: bool = False,
) -> ParsedResume:
    """Parse resume text into a :class:`ParsedResume`.

    ``layout_lines`` (from a PDF) take precedence over textual header
    detection when they yield any sections at all — visual headers are the
    more reliable signal when both are present.
    """
    clean = normalize_text(text)

    sections = split_sections_by_layout(layout_lines or []) or split_sections(clean)
    sections = {k.lower(): v for k, v in sections.items()}
    backend = "layout" if layout_lines and len(sections) > 1 else "regex"

    name, used_spacy = _extract_name(clean, spacy_model=spacy_model)
    if used_spacy:
        backend = f"spacy+{backend}"

    skills = extract_skills(clean, extra_terms=extra_skill_terms)
    if "skills" in sections:
        # The skills section is the highest-signal place to look; union it in
        # so a term that only appears there is not lost to a noisy body.
        skills = sorted(
            set(skills) | set(extract_skills(sections["skills"], extra_terms=extra_skill_terms)),
            key=str.lower,
        )

    education = _extract_education(sections.get("education", ""))

    experience: list[ExperienceEntry] = []
    for key in EXPERIENCE_SECTIONS:
        if key in sections:
            experience.extend(_extract_experience(sections[key]))
    if "extra-curricular" in sections:
        # Leadership and society roles are real experience; they just come
        # formatted differently, so they get their own extractor.
        experience.extend(_extract_leadership(sections["extra-curricular"]))

    projects: list[ProjectEntry] = []
    for key in PROJECT_SECTIONS:
        if key in sections:
            projects.extend(_extract_projects(sections[key]))

    warnings: list[str] = []
    if len(sections) <= 1:
        warnings.append("no_section_headers_detected")
    if not skills:
        warnings.append("no_skills_detected")
    if not education:
        warnings.append("no_education_detected")
    if not experience:
        warnings.append("no_experience_detected")
    if len(clean) < 500:
        warnings.append("very_short_document")
    if backend == "regex" and not name:
        warnings.append("name_not_found_install_nlp_extra")

    return ParsedResume(
        name=name,
        contacts=_extract_contacts(clean),
        skills=skills,
        education=education,
        experience=experience,
        projects=projects,
        raw_length=len(clean),
        sections_detected=sorted(sections),
        parse_warnings=warnings,
        backend=backend,
        used_ocr=used_ocr,
        source_name=source_name,
    )
