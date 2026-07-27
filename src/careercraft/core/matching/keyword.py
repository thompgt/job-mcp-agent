"""Keyword matching — the default strategy.

This is the load-bearing scorer, not a degraded mode. Semantic matching needs
sentence-transformers, which drags in ~2.5 GB of torch; requiring that for a
server people install with ``uvx`` is not viable, so the no-extras path has to
be genuinely good.

v1 had a fallback that returned ``matched_skills / total_resume_skills`` and
compared it against ``min_similarity=0.25`` — the same threshold used for
cosine similarity. Those two numbers are not on the same scale, so the
threshold meant something different depending on which code path ran. Here the
score is TF-IDF cosine (bounded 0-1, same shape as embedding cosine) blended
with skill coverage, so one threshold behaves consistently across strategies.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from careercraft.core.resume.skills import skill_overlap
from careercraft.models import Job, ParsedResume

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")

#: Words that appear in nearly every posting and every resume, so they add
#: length without adding signal.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
        "not",
        "no",
        "we",
        "you",
        "your",
        "our",
        "their",
        "his",
        "her",
        "its",
        "it",
        "they",
        "them",
        "he",
        "she",
        "i",
        "me",
        "my",
        "us",
        "who",
        "whom",
        "which",
        "what",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "only",
        "own",
        "same",
        "so",
        "too",
        "very",
        "just",
        "also",
        "about",
        "into",
        "over",
        "under",
        "again",
        "further",
        "once",
        "here",
        "there",
        "job",
        "role",
        "position",
        "company",
        "team",
        "work",
        "working",
        "experience",
        "years",
        "year",
        "candidate",
        "candidates",
        "opportunity",
        "opportunities",
        "apply",
        "applying",
        "application",
        "requirements",
        "responsibilities",
        "you'll",
        "we're",
        "strong",
        "excellent",
        "ability",
        "skills",
        "required",
        "preferred",
        "plus",
        "benefits",
        "including",
        "etc",
    ]
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def _tf_weights(tokens: list[str]) -> dict[str, float]:
    """Sub-linear term frequency, so one word repeated 40 times cannot dominate."""
    counts = Counter(tokens)
    return {term: 1.0 + math.log(count) for term, count in counts.items()}


def _idf(documents: list[list[str]]) -> dict[str, float]:
    n = len(documents)
    doc_freq: Counter[str] = Counter()
    for doc in documents:
        doc_freq.update(set(doc))
    # Smoothed IDF; always positive, so a term present in every document
    # contributes a little rather than cancelling out.
    return {term: math.log((n + 1) / (df + 0.5)) + 1.0 for term, df in doc_freq.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    smaller, larger = (a, b) if len(a) < len(b) else (b, a)
    dot = sum(weight * larger.get(term, 0.0) for term, weight in smaller.items())
    if dot == 0.0:
        return 0.0
    norm_a = math.sqrt(sum(w * w for w in a.values()))
    norm_b = math.sqrt(sum(w * w for w in b.values()))
    return dot / (norm_a * norm_b)


class KeywordScorer:
    """TF-IDF cosine plus skill coverage, fitted over one candidate set.

    IDF is computed from the postings being ranked. That makes the weighting
    adapt to the corpus at hand — in a batch of data-engineering roles, the
    word "data" correctly stops being informative.
    """

    #: How much of the final score comes from explicit skill overlap. Skills
    #: are the highest-precision signal in a resume, but they are sparse, so
    #: the free-text similarity has to carry the rest.
    SKILL_WEIGHT = 0.55

    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs
        self._job_texts = [job.to_search_text() for job in jobs]
        self._job_tokens = [tokenize(text) for text in self._job_texts]
        self._idf = _idf(self._job_tokens) if self._job_tokens else {}
        self._job_vectors = [self._vector(tokens) for tokens in self._job_tokens]

    def _vector(self, tokens: list[str]) -> dict[str, float]:
        return {term: tf * self._idf.get(term, 1.0) for term, tf in _tf_weights(tokens).items()}

    def score_all(self, resume: ParsedResume) -> list[tuple[float, list[str], list[str]]]:
        """Score every job. Returns ``(score, matched_skills, missing_skills)``."""
        resume_vector = self._vector(tokenize(resume.to_search_text()))
        results: list[tuple[float, list[str], list[str]]] = []

        for index in range(len(self._jobs)):
            text_score = _cosine(resume_vector, self._job_vectors[index])
            matched, missing = skill_overlap(resume.skills, self._job_texts[index])

            posting_skills = len(matched) + len(missing)
            if posting_skills:
                # Coverage on its own rewards *sparse* postings: a listing that
                # names one skill you happen to have scores a perfect 1.0,
                # beating one that names seven of yours alongside eight you
                # lack. Observed live — a generic "Online Data Analyst" ad
                # sharing one skill outranked an ML engineering role sharing
                # seven.
                #
                # So pair it with recall — how much of the candidate's skill
                # set the posting actually engages — and take the harmonic
                # mean. A posting has to be both a good fit for the candidate
                # and well covered by them to score highly, and one lucky
                # keyword cannot carry it.
                coverage = len(matched) / posting_skills
                recall = len(matched) / len(resume.skills) if resume.skills else 0.0
                skill_score = (
                    2 * coverage * recall / (coverage + recall) if (coverage + recall) else 0.0
                )
                score = self.SKILL_WEIGHT * skill_score + (1 - self.SKILL_WEIGHT) * text_score
            else:
                # The posting names no recognisable skills, so coverage is
                # undefined rather than zero — scoring it 0 would bury every
                # short or prose-heavy listing.
                score = text_score

            results.append((min(1.0, max(0.0, score)), matched, missing))
        return results


def _listing(items: list[str], limit: int) -> str:
    """Join a list, and say so when it was truncated.

    "Shares 7 skills: A, B, C, D, E" reads as a contradiction — either the
    count is wrong or two skills went missing. Saying "and 2 more" costs
    nothing and stops the sentence from undermining itself.
    """
    shown = ", ".join(items[:limit])
    extra = len(items) - limit
    return f"{shown} and {extra} more" if extra > 0 else shown


def explain(score: float, matched: list[str], missing: list[str]) -> str:
    """One line the host model can show a user without post-processing."""
    if matched:
        noun = "skill" if len(matched) == 1 else "skills"
        head = f"Shares {len(matched)} {noun}: {_listing(matched, 5)}"
    else:
        head = "No overlapping skills detected; ranked on wording similarity"
    if missing:
        head += f". Posting also asks for {_listing(missing, 4)}"
    return f"{head}. Score {score:.2f}."
