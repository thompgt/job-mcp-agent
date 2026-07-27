"""What this install can actually do.

Exposed as an MCP resource so a host model can read it once and stop offering
features that would only fail. The whole optional-extra design depends on
this being honest and cheap to compute: nothing here imports a heavy module,
it only asks whether one is importable.
"""

from __future__ import annotations

import platform

from careercraft.core.matching.embedding import is_available as embeddings_available
from careercraft.core.matching.service import default_strategy
from careercraft.core.resume.extract import extraction_backends
from careercraft.models import Capabilities, Capability


def _spacy_present() -> bool:
    from importlib.util import find_spec

    try:
        return find_spec("spacy") is not None
    except (ImportError, ValueError):  # pragma: no cover
        return False


def collect(*, transport: str = "stdio", ollama_reachable: bool | None = None) -> Capabilities:
    """Build the capability report.

    ``ollama_reachable`` is passed in rather than probed, because probing is a
    network call and this is called from resource reads that should stay fast.
    """
    backends = extraction_backends()
    entries = [
        Capability(
            name="pdf_text",
            available=backends["pdf"],
            detail="Extract text from PDF resumes.",
            enable_with=None if backends["pdf"] else "pip install 'careercraft-mcp[pdf]'",
        ),
        Capability(
            name="pdf_layout",
            available=backends["pdf_layout"],
            detail="Detect sections from font size and weight, not just text headers.",
            enable_with=None if backends["pdf_layout"] else "pip install 'careercraft-mcp[pdf]'",
        ),
        Capability(
            name="docx",
            available=backends["docx"],
            detail="Read Word resumes.",
            enable_with=None if backends["docx"] else "pip install 'careercraft-mcp[pdf]'",
        ),
        Capability(
            name="ocr",
            available=backends["ocr"],
            detail="Fall back to OCR for scanned PDFs. Also needs the tesseract binary.",
            enable_with=None if backends["ocr"] else "pip install 'careercraft-mcp[ocr]'",
        ),
        Capability(
            name="nlp_names",
            available=_spacy_present(),
            detail="Use spaCy NER to find a candidate name that is not on the first lines.",
            enable_with=None if _spacy_present() else "pip install 'careercraft-mcp[nlp]'",
        ),
        Capability(
            name="semantic_matching",
            available=embeddings_available(),
            detail="Rank jobs by embedding similarity rather than keyword overlap.",
            enable_with=(
                None
                if embeddings_available()
                else "pip install 'careercraft-mcp[embeddings]'  # ~2.5 GB"
            ),
        ),
        Capability(
            name="keyword_matching",
            available=True,
            detail="TF-IDF and skill-overlap ranking. Always available.",
        ),
        Capability(
            name="llm_cover_letters",
            available=bool(ollama_reachable),
            detail="Write cover letter prose with a local Ollama model.",
            enable_with=(
                None
                if ollama_reachable
                else "Install Ollama from https://ollama.com, then `ollama serve`"
            ),
        ),
        Capability(
            name="letter_briefs",
            available=True,
            detail=(
                "Return a grounded brief (themes, evidence, company hooks, paragraph plan) "
                "for the calling model to write from. Always available."
            ),
        ),
    ]

    from careercraft import __version__

    return Capabilities(
        version=__version__,
        python=platform.python_version(),
        transport=transport,
        capabilities=entries,
        default_match_strategy=default_strategy(),  # type: ignore[arg-type]
    )
