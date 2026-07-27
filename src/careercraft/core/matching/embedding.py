"""Semantic matching via sentence-transformers.

Optional, and imported lazily: this path pulls torch. The model is cached
process-wide because loading it costs a few seconds and hundreds of megabytes
of RAM — doing that per request would be pathological.

Encoding is CPU-bound and torch is not safe to drive from several threads at
once, so callers must run :meth:`EmbeddingScorer.score_all` off the event loop
under a single-slot capacity limiter. :mod:`careercraft.core.matching.service`
does that.
"""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from careercraft.core.resume.skills import skill_overlap
from careercraft.errors import DependencyMissing
from careercraft.models import Job, ParsedResume

_ENCODERS: dict[str, Any] = {}


def is_available() -> bool:
    try:
        return find_spec("sentence_transformers") is not None and find_spec("numpy") is not None
    except (ImportError, ValueError):  # pragma: no cover - malformed install
        return False


def get_encoder(model_name: str) -> Any:
    """Load and cache the encoder. Blocks for seconds on first call."""
    if not is_available():
        raise DependencyMissing("Semantic job matching", "embeddings")
    if model_name not in _ENCODERS:
        from sentence_transformers import SentenceTransformer

        _ENCODERS[model_name] = SentenceTransformer(model_name)
    return _ENCODERS[model_name]


class EmbeddingScorer:
    """Cosine similarity between resume and posting embeddings."""

    def __init__(self, jobs: list[Job], *, model_name: str) -> None:
        self._jobs = jobs
        self._job_texts = [job.to_search_text() for job in jobs]
        self._model_name = model_name

    def score_all(self, resume: ParsedResume) -> list[tuple[float, list[str], list[str]]]:
        import numpy as np

        encoder = get_encoder(self._model_name)
        # normalize_embeddings turns the dot product into cosine directly and
        # avoids the divide-by-zero guard v1 needed.
        resume_vec = encoder.encode(
            resume.to_search_text(), convert_to_numpy=True, normalize_embeddings=True
        )
        job_vecs = encoder.encode(
            self._job_texts, convert_to_numpy=True, normalize_embeddings=True, batch_size=32
        )
        sims = np.asarray(job_vecs @ resume_vec, dtype=float).reshape(-1)

        results: list[tuple[float, list[str], list[str]]] = []
        for index, similarity in enumerate(sims):
            matched, missing = skill_overlap(resume.skills, self._job_texts[index])
            # Cosine over these models is effectively in [0, 1] for related
            # text, but clamp so the contract in the model schema holds.
            results.append((min(1.0, max(0.0, float(similarity))), matched, missing))
        return results


def explain(score: float, matched: list[str], missing: list[str]) -> str:
    parts = [f"Semantic similarity {score:.2f}"]
    if matched:
        parts.append(f"shared skills: {', '.join(matched[:5])}")
    if missing:
        parts.append(f"gaps: {', '.join(missing[:4])}")
    return "; ".join(parts) + "."
