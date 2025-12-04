# server/app/services/resume_parser.py
from __future__ import annotations

"""
Resume parsing service.

Improvements over the original:
- Configurable spaCy model via SPACY_MODEL_NAME env var
- Extendable skill vocabulary via SKILL_VOCAB_PATH env var
- More robust PDF loading with explicit OCR flag
- Extra metadata in output (skills_count, experience_count, education_count,
  sections_detected, parse_warnings, used_ocr, source_path)
- Keeps the original public API: load_text_from_file, parse_resume_text,
  parse_resume_file
"""

# stdlib
import os
import re
import difflib
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# nlp & parsing libs
import spacy
from spacy.matcher import PhraseMatcher
from pypdf import PdfReader
from docx import Document
import fitz  # PyMuPDF

# =========================
# env toggles / config
# =========================

# FAST_PARSE=1 -> skip OCR and layout segmentation for speed on clean PDFs
FAST_PARSE = os.getenv("FAST_PARSE", "0") == "1"

# spaCy model can be swapped without code changes (e.g. en_core_web_trf)
SPACY_MODEL_NAME = os.getenv("SPACY_MODEL_NAME", "en_core_web_sm")

# Optional external skill vocab file (one skill term per line)
SKILL_VOCAB_PATH = os.getenv("SKILL_VOCAB_PATH")

# Track last load OCR usage (used for metadata)
_LAST_LOAD_USED_OCR: bool = False

# =========================
# lazy spaCy and matcher
# =========================
_NLP: Optional[spacy.language.Language] = None
_MATCHER: Optional[PhraseMatcher] = None


def _get_nlp() -> spacy.language.Language:
    """Lazy-load spaCy model, configurable by env."""
    global _NLP
    if _NLP is None:
        _NLP = spacy.load(SPACY_MODEL_NAME)
        # ensure we have sentence boundaries even in small models
        if "sentencizer" not in _NLP.pipe_names:
            _NLP.add_pipe("sentencizer")
    return _NLP


# Base skill dictionary (extendable via SKILL_VOCAB_PATH)
_BASE_SKILL_TERMS = [
    # programming languages
    "python", "java", "javascript", "typescript", "c++", "c", "go", "rust", "sql", "r",
    # data / ml
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch",
    "spark", "hadoop", "airflow", "dbt",
    # cloud / infra
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "linux",
    # data stores
    "postgresql", "mysql", "snowflake", "bigquery", "redshift",
    # tools / libs
    "git", "regex", "spacy", "fastapi",
]


def _load_skill_terms() -> List[str]:
    """Combine base skill terms with optional extra vocab from file."""
    terms = list(_BASE_SKILL_TERMS)
    if SKILL_VOCAB_PATH:
        path = Path(SKILL_VOCAB_PATH)
        if path.exists():
            try:
                extra = [
                    line.strip()
                    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if line.strip()
                ]
                terms.extend(extra)
            except Exception:
                # fail silently; we still have base terms
                pass
    # dedupe while preserving order
    seen = set()
    uniq: List[str] = []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(t)
    return uniq


def _get_matcher() -> PhraseMatcher:
    """Lazy-init PhraseMatcher for skills."""
    global _MATCHER
    if _MATCHER is None:
        nlp = _get_nlp()
        _MATCHER = PhraseMatcher(nlp.vocab, attr="LOWER")
        for term in _load_skill_terms():
            _MATCHER.add("SKILLS", [nlp.make_doc(term)])
    return _MATCHER


# =========================
# file readers with OCR fallback
# =========================

def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _read_txt(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def _ocr_image_pil(img) -> str:
    import pytesseract
    return pytesseract.image_to_string(img)


def _ocr_pdf(path: Path) -> str:
    from pdf2image import convert_from_path
    pages = convert_from_path(str(path))
    return "\n".join(_ocr_image_pil(pg) for pg in pages)


def load_text_from_file(path: str | Path) -> str:
    """
    Unified loader with optional OCR for image-like PDFs.

    Public API kept the same: returns text string.
    Internally we also update _LAST_LOAD_USED_OCR for metadata.
    """
    global _LAST_LOAD_USED_OCR
    _LAST_LOAD_USED_OCR = False

    path = Path(path)
    sfx = path.suffix.lower()

    if sfx == ".pdf":
        # fast path: just pypdf
        if FAST_PARSE:
            return _read_pdf(path)

        text = _read_pdf(path)
        # If text is suspiciously short, attempt OCR as fallback
        if not text or len(text.strip()) < 20:
            try:
                text = _ocr_pdf(path)
                if text and len(text.strip()) > 0:
                    _LAST_LOAD_USED_OCR = True
            except Exception:
                # if OCR fails, just return whatever we had
                pass
        return text

    if sfx in (".docx", ".doc"):
        return _read_docx(path)

    # default: plain text
    return _read_txt(path)


# =========================
# regexes
# =========================

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-]*)?(?:\(?\d{2,4}\)?[\s\-]*){2,4}\d{2,4}")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/[A-Za-z0-9_/\-]+", re.I)
GITHUB_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_\-/.]+", re.I)

DEGREE_RE = re.compile(
    r"\b(B\.?Sc|B\.?S|M\.?Sc|M\.?S|B\.?Eng|M\.?Eng|Ph\.?D|Bachelor|Master|Doctor|BA|MA)\b",
    re.I,
)
YEAR_RE = re.compile(r"\b(20\d{2}|19\d{2})\b")

MONTH_RX = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
YEAR_ONLY = r"(?:19|20)\d{2}"
RANGE_SEP = r"\s*[—\-–]\s*"
PRESENT = r"(?:Present|PRESENT|present)"
DATE_RANGE_RE = re.compile(
    rf"(?:{MONTH_RX}\s+\d{{4}}|{YEAR_ONLY})"
    rf"{RANGE_SEP}"
    rf"(?:{MONTH_RX}\s+\d{{4}}|{YEAR_ONLY}|{PRESENT})",
    re.I,
)

SECTION_RE = re.compile(
    r"""(?im)^\s*(
        profile|
        contact|contacts|
        education|
        work\s+experience|
        professional\s+experience|
        experience|
        internship\s+experience|
        leadership\s*&\s*projects|
        additional\s+projects|
        academic\s+projects|
        projects|
        skills|
        certifications|
        extra[-\s]?curricular
    )\s*[:\-]?\s*$""",
    re.X,
)

CANONICAL_SECTIONS = {
    "profile": ["profile", "summary", "about me"],
    "contact": ["contact", "contacts", "contact details"],
    "skills": ["skills", "technical skills", "key skills"],
    "education": ["education", "academics", "academic background"],
    "work experience": ["work experience", "professional experience", "experience", "employment"],
    "internship experience": ["internship experience", "internships", "internship"],
    "academic projects": ["academic projects", "projects", "course projects"],
    "certifications": ["certifications", "certificates", "licenses"],
    "extra-curricular": ["extra-curricular activities", "extracurricular", "activities", "volunteering"],
    "awards": ["awards", "honors", "achievements"],
}
ALL_HEADER_VARIANTS = {
    alias: key
    for key, aliases in CANONICAL_SECTIONS.items()
    for alias in ([key] + aliases)
}

NAME_BLACKLIST = {
    "education", "experience", "work experience", "skills", "projects",
    "profile", "contact", "contacts", "summary",
}

BULLET_HEAD = re.compile(r"^[•\-\*\u2022]\s*")
MONTH_WORD = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*$", re.I)


# =========================
# contact / name / skills
# =========================

def _norm_url(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    return u if u.startswith(("http://", "https://")) else "https://" + u


def _extract_contacts(text: str) -> Dict[str, Optional[str]]:
    def g(rx):
        m = rx.search(text)
        return m.group(0) if m else None

    return {
        "email": g(EMAIL_RE),
        "phone": g(PHONE_RE),
        "linkedin": _norm_url(g(LINKEDIN_RE)),
        "github": _norm_url(g(GITHUB_RE)),
    }


def _looks_like_name(line: str) -> bool:
    t = re.sub(r"[^A-Za-z\s\-']", " ", line).strip()
    if not t:
        return False
    words = t.split()
    if not (1 <= len(words) <= 4):
        return False
    if t.lower() in NAME_BLACKLIST:
        return False
    return all(2 <= len(w) <= 20 and re.fullmatch(r"[A-Za-z\-']+", w) for w in words)


def _extract_name(doc: "spacy.tokens.Doc") -> Optional[str]:
    # First try the top few lines (most resumes)
    for ln in [ln.strip() for ln in doc.text.splitlines()[:5] if ln.strip()]:
        if _looks_like_name(ln):
            return ln.title() if ln.isupper() else ln
    # Fallback to PERSON entities
    for ent in doc.ents:
        if ent.label_ == "PERSON" and ent.text.lower() not in NAME_BLACKLIST:
            return ent.text.strip()
    return None


def _extract_skills(doc: "spacy.tokens.Doc") -> List[str]:
    # Sentence-level matching to reduce false positives
    matcher = _get_matcher()
    skills = set()
    for sent in doc.sents:
        for _, s, e in matcher(sent):
            skills.add(doc[s:e].text.lower())
    return sorted(skills)


# =========================
# text-based section split
# =========================

def _looks_like_header(line: str) -> bool:
    t = line.strip()
    if not t:
        return False
    # all caps or mostly caps, short-ish line
    return bool(re.fullmatch(r"[A-Z0-9 &/\-]{4,}", t))


def _normalize_header_name(name: str) -> Optional[str]:
    n = name.lower()
    if "education" in n:
        return "education"
    if "work" in n and "experience" in n:
        return "work experience"
    if "intern" in n and "experience" in n:
        return "internship experience"
    if "experience" in n:
        return "experience"
    if "profile" in n:
        return "profile"
    if "contact" in n:
        return "contact"
    if "skill" in n:
        return "skills"
    if "academic" in n and "project" in n:
        return "academic projects"
    if "project" in n:
        return "projects"
    if "certif" in n:
        return "certifications"
    if "extra" in n and "curricular" in n:
        return "extra-curricular"
    return None


def _split_sections(text: str) -> Dict[str, str]:
    """
    Split resume into sections using explicit headers (e.g. EDUCATION, EXPERIENCE).
    """
    lines = text.splitlines(keepends=True)
    full_text = "".join(lines)
    marks: List[Tuple[str, int]] = []

    # Regex-based explicit headers
    for m in SECTION_RE.finditer(full_text):
        marks.append((m.group(1).lower(), m.end()))

    # All-caps or header-like lines
    offset = 0
    for ln in lines:
        raw = ln.rstrip("\n")
        if _looks_like_header(raw):
            nm = _normalize_header_name(raw.strip())
            if nm:
                marks.append((nm, offset + len(ln)))
        offset += len(ln)

    marks = sorted(set(marks), key=lambda x: x[1])
    if not marks:
        return {"full": full_text}

    sections: Dict[str, str] = {}
    for i, (nm, start_pos) in enumerate(marks):
        end_pos = marks[i + 1][1] if i + 1 < len(marks) else len(full_text)
        chunk = full_text[start_pos:end_pos].lstrip("\n").rstrip()
        sections[nm] = chunk
    return sections


# =========================
# layout-based section split
# =========================

def _pdf_lines_with_layout(path: Path) -> List[Dict]:
    """Extract per-line text with basic font features from PDF via PyMuPDF."""
    doc = fitz.open(str(path))
    lines = []
    try:
        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for b in blocks:
                if "lines" not in b:
                    continue
                for ln in b["lines"]:
                    texts, sizes, flags = [], [], []
                    for sp in ln.get("spans", []):
                        if sp.get("text"):
                            texts.append(sp["text"])
                        sizes.append(sp.get("size", 0))
                        flags.append(sp.get("flags", 0))
                    if not texts:
                        continue
                    t = "".join(texts).strip()
                    if not t:
                        continue
                    avg_size = sum(sizes) / max(len(sizes), 1)
                    is_bold = any((f & 1) == 1 for f in flags)
                    bbox = ln.get("bbox")
                    lines.append({"text": t, "size": avg_size, "bold": is_bold, "bbox": bbox})
    finally:
        doc.close()
    return lines


def _normalize_header_freeform(name: str) -> Optional[str]:
    s = re.sub(r"[^A-Za-z0-9 &/\-]", " ", name).strip().lower()
    if s in ALL_HEADER_VARIANTS:
        return ALL_HEADER_VARIANTS[s]
    s = re.sub(r"\s+", " ", s)
    best_key, best_sim = None, 0.0
    for key, aliases in CANONICAL_SECTIONS.items():
        pool = [key] + aliases
        sim = max(difflib.SequenceMatcher(None, s, x).ratio() for x in pool)
        if sim > best_sim:
            best_sim, best_key = sim, key
    return best_key if best_sim >= 0.65 else None


def _detect_section_headers_from_layout(lines: List[Dict]) -> List[Tuple[str, int]]:
    if not lines:
        return []
    sizes = [x["size"] for x in lines]
    median = sorted(sizes)[len(sizes) // 2]
    big_threshold = median * 1.15

    headers = []
    for idx, row in enumerate(lines):
        text = row["text"]
        size = row["size"]
        is_big = size >= big_threshold
        letters = [c for c in text if c.isalpha()]
        is_caps = (len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.7)
        is_short = len(text.split()) <= 6
        has_rule_word = bool(
            re.search(
                r"(experience|education|profile|project|skill|certif|intern|activity|activities)",
                text, re.I
            )
        )
        if (is_big or row["bold"]) and (is_caps or is_short or has_rule_word):
            canon = _normalize_header_freeform(text)
            if canon:
                headers.append((canon, idx))

    dedup: List[Tuple[str, int]] = []
    for k, idx in sorted(headers, key=lambda x: x[1]):
        if dedup and dedup[-1][0] == k and idx - dedup[-1][1] <= 2:
            continue
        dedup.append((k, idx))
    return dedup


def _split_sections_by_layout(path: Path) -> Optional[Dict[str, str]]:
    """
    Use PDF layout segmentation to infer sections.

    This can capture resumes where headers are purely visual (font size/bold),
    not explicit all-caps text.
    """
    try:
        lines = _pdf_lines_with_layout(path)
        if not lines:
            return None
        headers = _detect_section_headers_from_layout(lines)
        if not headers:
            return None
        all_text = "\n".join(l["text"] for l in lines)
        offsets, pos = [], 0
        for l in lines:
            offsets.append(pos)
            pos += len(l["text"]) + 1

        out: Dict[str, str] = {}
        for i, (key, line_idx) in enumerate(headers):
            start = offsets[min(line_idx + 1, len(offsets) - 1)]
            end = offsets[headers[i + 1][1]] if i + 1 < len(headers) else len(all_text)
            chunk = all_text[start:end].strip()
            if chunk:
                out[key] = (out.get(key, "") + ("\n\n" if key in out else "") + chunk).strip()
        return out or None
    except Exception:
        return None


# =========================
# education / experience / projects utils
# =========================

def _extract_education(section: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for line in section.splitlines():
        deg = DEGREE_RE.search(line)
        yrs = YEAR_RE.findall(line)
        if deg or yrs:
            rows.append(
                {
                    "text": line.strip(),
                    "degree": deg.group(0) if deg else None,
                    "years": (yrs[-2:] if yrs else None),
                }
            )
    return rows


_HEADER_NAMES = {
    "professional experience", "work experience", "experience",
    "internship experience", "leadership & projects", "additional projects",
    "academic projects", "projects", "education", "skills",
    "profile", "contact", "contacts", "extra-curricular",
}


def _reflow_lines_for_highlights(lines: List[str]) -> List[str]:
    """Join wrapped lines into sentence-like bullets."""
    END = re.compile(r"[.;:)\]%]\s*$")
    out: List[str] = []
    buf: List[str] = []

    def flush():
        if buf:
            merged = " ".join(s.strip() for s in buf).strip()
            # fix spacing artifacts like '120K +' or '15K +'
            merged = re.sub(r"\s*\+\s*", " + ", merged)
            merged = re.sub(r"\s{2,}", " ", merged)
            out.append(merged)
            buf.clear()

    for ln in lines:
        if not buf:
            buf.append(ln)
        else:
            if not END.search(buf[-1]):
                buf.append(ln)
            else:
                flush()
                buf.append(ln)
    flush()
    return [s for s in out if len(s) >= 3]


def _location_like_text() -> re.Pattern:
    return re.compile(
        r"^(?:[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s?(?:[A-Z]{2}|[A-Z][a-z]+)|"
        r"(?:Seoul|South Korea|New York, NY|New York|NY|KR))$",
        re.I,
    )


def _clean_title(t: str) -> str:
    # remove month-only false titles like 'Jun', 'Oct', 'May'
    t = t.strip(" -—–|,")
    if MONTH_WORD.fullmatch(t):
        return ""
    return t


def _extract_experience(section: str) -> List[Dict[str, str]]:
    # build experience blocks: organization -> title(+period) -> highlights
    raw = [ln.strip() for ln in section.splitlines()]
    lines = [BULLET_HEAD.sub("", ln).strip() for ln in raw if ln.strip()]
    exps: List[Dict[str, str]] = []
    cur: Optional[Dict[str, str]] = None

    def is_header_like(s: str) -> bool:
        t = s.strip().lower()
        return (t in _HEADER_NAMES) or (_looks_like_header(s) and _normalize_header_name(s) is not None)

    company_like = re.compile(r"^[A-Z][A-Za-z0-9@&×/.,\-\u2013\u2014 ]{1,80}$")
    role_plus_date = re.compile(rf"^(.+?)\s+({DATE_RANGE_RE.pattern})$", re.I)
    date_range_only = re.compile(rf"^\s*({DATE_RANGE_RE.pattern})\s*$", re.I)
    location_like = _location_like_text()
    role_keywords = re.compile(
        r"(engineer|tutor|manager|lead|leader|board|analyst|developer|research|intern|specialist)",
        re.I,
    )

    def flush():
        nonlocal cur
        if cur:
            cur["organization"] = cur.get("organization", "").strip()
            cur["title"] = cur.get("title", "").strip()
            cur["period"] = (cur.get("period") or "").strip() or None
            highlights_raw = [s for s in cur.get("desc_buf", []) if s]
            cur.pop("desc_buf", None)
            cur["highlights"] = _reflow_lines_for_highlights(highlights_raw)
            if cur["organization"] or cur["title"] or cur["highlights"]:
                exps.append(cur)
        cur = None

    i = 0
    while i < len(lines):
        ln = lines[i]

        if is_header_like(ln):
            i += 1
            continue

        # merge pattern: role-only -> location -> (role+date | date-only)
        if role_keywords.search(ln) and not date_range_only.match(ln):
            if (
                i + 2 < len(lines)
                and location_like.match(lines[i + 1])
                and (role_plus_date.match(lines[i + 2]) or date_range_only.match(lines[i + 2]))
            ):
                if cur:
                    flush()
                cur = {"organization": f"{ln}, {lines[i + 1]}", "title": "", "period": None, "desc_buf": []}
                if role_plus_date.match(lines[i + 2]):
                    m3 = role_plus_date.match(lines[i + 2])
                    cur["title"] = _clean_title(m3.group(1))
                    cur["period"] = m3.group(2).strip()
                else:
                    cur["title"] = _clean_title(ln)
                    cur["period"] = date_range_only.match(lines[i + 2]).group(1).strip()
                i += 3
                continue

        m = role_plus_date.match(ln)
        if m:
            if cur is None:
                cur = {"organization": "", "title": "", "period": None, "desc_buf": []}
            cur["title"] = _clean_title(m.group(1))
            cur["period"] = m.group(2).strip()
            i += 1
            continue

        dm = date_range_only.match(ln)
        if dm:
            if cur is None:
                cur = {"organization": "", "title": "", "period": None, "desc_buf": []}
            if (
                not cur.get("title")
                and i > 0
                and role_keywords.search(lines[i - 1])
                and not date_range_only.match(lines[i - 1])
            ):
                cur["title"] = _clean_title(lines[i - 1])
            cur["period"] = dm.group(1).strip()
            i += 1
            continue

        if company_like.match(ln) and not ln.islower() and not role_plus_date.search(ln) and not role_keywords.search(ln):
            if cur:
                flush()
            cur = {"organization": ln, "title": "", "period": None, "desc_buf": []}
            if i + 1 < len(lines) and location_like.match(lines[i + 1]):
                cur["organization"] = f"{cur['organization']}, {lines[i + 1]}"
                i += 1
            i += 1
            continue

        if role_keywords.search(ln) and not date_range_only.match(ln):
            if i + 1 < len(lines) and date_range_only.match(lines[i + 1]):
                if cur is None:
                    cur = {"organization": "", "title": "", "period": None, "desc_buf": []}
                cur["title"] = _clean_title(ln)
                cur["period"] = date_range_only.match(lines[i + 1]).group(1).strip()
                i += 2
                continue
            # role-only that begins a new block
            if cur and cur.get("desc_buf"):
                flush()
            if cur is None:
                cur = {"organization": "", "title": "", "period": None, "desc_buf": []}
            if not cur.get("title"):
                cur["title"] = _clean_title(ln)
            else:
                cur["desc_buf"].append(ln)
            i += 1
            continue

        if location_like.match(ln):
            if cur and not cur.get("organization"):
                cur["organization"] = ln
            i += 1
            continue

        if cur is None:
            cur = {"organization": "", "title": "", "period": None, "desc_buf": []}
        cur["desc_buf"].append(ln)
        i += 1

    flush()
    return exps


def _extract_projects(section: str) -> List[Dict[str, Optional[str]]]:
    # parse projects from project-like sections, keeping headers as names and verb-led lines as highlights
    lines = [BULLET_HEAD.sub("", ln).strip() for ln in section.splitlines() if ln.strip()]
    out: List[Dict[str, Optional[str]]] = []
    if not lines:
        return out

    date_only = re.compile(rf"^\s*({DATE_RANGE_RE.pattern})\s*$", re.I)
    VERB_START = re.compile(
        r"^(Built|Designed|Orchestrated|Implemented|Provisioned|Containerized|Drafted|Prototyped|Defined|"
        r"Planned|Created|Developed|Improved|Set\s+up|Established)\b",
        re.I,
    )
    role_keywords = re.compile(
        r"(engineer|tutor|leader|board|analyst|developer|manager|intern|collaborator|co[- ]founder|research)",
        re.I,
    )
    location_like = _location_like_text()

    def looks_like_header(s: str) -> bool:
        if date_only.match(s) or location_like.match(s):
            return False
        if VERB_START.match(s):
            return False
        if " — " in s or " - " in s:
            return True
        if s[:1].isupper() and not s.endswith(".") and len(s) <= 120:
            return True
        return False

    blocks: List[List[str]] = []
    buf: List[str] = []
    for ln in lines:
        if looks_like_header(ln):
            if buf:
                blocks.append(buf[:])
                buf.clear()
            buf.append(ln)
        else:
            if not buf:
                buf.append(ln)
            else:
                buf.append(ln)
    if buf:
        blocks.append(buf)

    def block_to_project(b: List[str]) -> Optional[Dict[str, Optional[str]]]:
        if not b:
            return None
        header = b[0].strip()
        name = header
        role = None
        location = None
        period = None

        if "," in header:
            tail = header.split(",")[-1].strip()
            if location_like.match(tail):
                location = tail
                name = ",".join(header.split(",")[:-1]).strip()

        mdate = DATE_RANGE_RE.search(header) or (DATE_RANGE_RE.search(b[1]) if len(b) > 1 else None)
        if mdate:
            period = mdate.group(0)

        mrole = role_keywords.search(header)
        if mrole:
            role = mrole.group(0).title()

        highlights_raw = [s for s in b[1:] if not date_only.match(s) and not location_like.match(s)]
        highlights = _reflow_lines_for_highlights(highlights_raw)

        if VERB_START.match(name):
            if highlights:
                first = highlights.pop(0)
                name = "Project"
                highlights.insert(0, first)

        return {
            "name": name,
            "role": role,
            "location": location,
            "period": period,
            "highlights": highlights,
        }

    for b in blocks:
        pj = block_to_project(b)
        if pj and (pj["name"] or pj["highlights"]):
            out.append(pj)

    out = [p for p in out if p.get("name") or p.get("highlights")]
    return out


def _extract_leadership_roles(section: str) -> List[Dict[str, str]]:
    # parse leadership roles like "Executive Board" into experience-like blocks
    raw = [ln.strip() for ln in section.splitlines()]
    lines = [BULLET_HEAD.sub("", ln).strip() for ln in raw if ln.strip()]
    date_only = re.compile(rf"^\s*({DATE_RANGE_RE.pattern})\s*$", re.I)
    role_keywords = re.compile(r"(executive|president|board|chair|lead|leader|captain)", re.I)
    location_like = _location_like_text()

    exps: List[Dict[str, str]] = []
    cur: Optional[Dict[str, str]] = None

    def flush():
        nonlocal cur
        if cur:
            cur["organization"] = cur.get("organization", "").strip()
            cur["title"] = cur.get("title", "").strip()
            cur["period"] = (cur.get("period") or "").strip() or None
            highlights_raw = [s for s in cur.get("desc_buf", []) if s]
            cur.pop("desc_buf", None)
            cur["highlights"] = _reflow_lines_for_highlights(highlights_raw)
            if cur["organization"] or cur["title"] or cur["highlights"]:
                exps.append(cur)
        cur = None

    i = 0
    while i < len(lines):
        ln = lines[i]

        if _looks_like_header(ln):
            i += 1
            continue

        if role_keywords.search(ln) and not date_only.match(ln):
            if cur:
                flush()
            cur = {"organization": "", "title": ln.strip(" -—–|,"), "period": None, "desc_buf": []}
            i += 1
            continue

        dm = date_only.match(ln)
        if dm:
            if cur is None:
                cur = {"organization": "", "title": "", "period": None, "desc_buf": []}
            cur["period"] = dm.group(1).strip()
            i += 1
            continue

        if location_like.match(ln):
            if cur and not cur.get("organization"):
                cur["organization"] = ln
            i += 1
            continue

        if cur is None:
            cur = {"organization": "", "title": "", "period": None, "desc_buf": []}
        cur["desc_buf"].append(ln)
        i += 1

    flush()
    return exps


# =========================
# top-level parse
# =========================

def parse_resume_text(text: str, sections_override: Optional[Dict[str, str]] = None) -> Dict:
    """
    Main parsing entrypoint for plain text resumes.

    Returns a dict with:
      - name, contacts, skills, education, experience, projects
      - raw_length
      - skills_count, experience_count, education_count
      - sections_detected, parse_warnings
    """
    # light normalize
    clean = re.sub(r"[ \t]+", " ", text.replace("\r", "\n"))
    clean = re.sub(r"[\u2022\u2023\u25E6\u2043\u2219]", "•", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)

    nlp = _get_nlp()
    doc = nlp(clean)

    contacts = _extract_contacts(clean)
    name = _extract_name(doc)
    skills = _extract_skills(doc)

    # sections: either forced override (layout) or regex-based
    sections_src = sections_override if sections_override else _split_sections(clean)
    sections = {(k.lower() if k else k): v for k, v in sections_src.items()}

    education = _extract_education(sections.get("education", "")) if "education" in sections else []

    # experience from experience-like sections only
    experience: List[Dict[str, str]] = []
    for key in ("work experience", "professional experience", "experience", "internship experience"):
        if key in sections:
            experience.extend(_extract_experience(sections[key]))

    # leadership roles as experience
    if "leadership & projects" in sections:
        experience.extend(_extract_leadership_roles(sections["leadership & projects"]))

    # projects from project-like sections
    projects: List[Dict[str, Optional[str]]] = []
    for key in ("leadership & projects", "projects", "additional projects", "academic projects"):
        if key in sections:
            projects.extend(_extract_projects(sections[key]))

    sections_detected = list(sections.keys())
    result: Dict[str, object] = {
        "name": name,
        "contacts": contacts,
        "skills": sorted(skills),
        "education": education,
        "experience": experience,
        "projects": projects,
        "raw_length": len(clean),
        "skills_count": len(skills),
        "experience_count": len(experience),
        "education_count": len(education),
        "sections_detected": sections_detected,
    }

    # lightweight quality / warning flags
    warnings: List[str] = []
    if len(sections_detected) <= 1:
        warnings.append("no_section_headers_detected")
    if not skills:
        warnings.append("no_skills_detected")
    if not education:
        warnings.append("no_education_detected")
    if not experience:
        warnings.append("no_experience_detected")
    if len(clean) < 500:
        warnings.append("very_short_document")
    result["parse_warnings"] = warnings

    return result


def parse_resume_file(path: str | Path) -> Dict:
    """
    Main entry used by other services / FastAPI routes.

    - Loads text (with optional OCR)
    - Uses layout-based segmentation for PDFs when available
    - Calls parse_resume_text(...)
    - Adds used_ocr and source_path metadata
    """
    path = Path(path)
    text = load_text_from_file(path)

    sections_override = None
    if path.suffix.lower() == ".pdf" and not FAST_PARSE:
        # layout-based segmentation; if it fails, we fall back to regex split
        sections_override = _split_sections_by_layout(path)

    result = parse_resume_text(text, sections_override=sections_override)
    result["used_ocr"] = _LAST_LOAD_USED_OCR
    result["source_path"] = str(path)
    return result


# =========================
# dev cli
# =========================
if __name__ == "__main__":
    import json
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="path to resume file (pdf/docx/txt)")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    data = parse_resume_file(args.input)
    print(
        json.dumps(
            data,
            indent=2 if args.pretty else None,
            ensure_ascii=False,
        )
    )
