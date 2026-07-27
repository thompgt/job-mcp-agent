"""Strategy selection and ranking."""

from __future__ import annotations

from careercraft.core.matching import embedding, keyword
from careercraft.core.matching.heuristics import candidate_is_junior, filter_jobs
from careercraft.errors import DependencyMissing
from careercraft.models import Job, JobMatch, MatchResult, ParsedResume, Strategy


def available_strategies() -> list[str]:
    return ["embedding", "keyword"] if embedding.is_available() else ["keyword"]


def default_strategy() -> str:
    """Semantic when it is installed, keyword otherwise.

    ``auto`` resolves through here rather than failing, so the same tool call
    works on a minimal install and a full one — the caller learns which ran
    from ``MatchResult.strategy_used``.
    """
    return "embedding" if embedding.is_available() else "keyword"


def rank_jobs(
    resume: ParsedResume,
    jobs: list[Job],
    *,
    top_k: int = 10,
    min_score: float = 0.25,
    strategy: Strategy = "auto",
    filter_seniority: bool = True,
    embedding_model: str = "all-MiniLM-L6-v2",
) -> MatchResult:
    """Rank ``jobs`` for ``resume``.

    Synchronous and CPU-bound. The embedding path can block for seconds, so
    async callers must dispatch this to a worker thread.
    """
    notes: list[str] = []
    resolved = default_strategy() if strategy == "auto" else strategy

    if resolved == "embedding" and not embedding.is_available():
        if strategy == "embedding":
            raise DependencyMissing("Semantic job matching", "embeddings")
        resolved = "keyword"

    junior = candidate_is_junior(resume)
    kept, dropped = filter_jobs(resume, jobs, filter_seniority=filter_seniority)
    if dropped:
        notes.append(
            f"Filtered out {dropped} posting(s) as senior-level or requiring a higher degree."
        )

    if not kept:
        if jobs:
            notes.append(
                "Every posting was filtered out by the seniority and degree heuristics. "
                "Re-run with filter_seniority=false to see them anyway."
            )
        return MatchResult(
            matches=[],
            strategy_used=resolved,  # type: ignore[arg-type]
            candidate_is_junior=junior,
            jobs_considered=len(jobs),
            jobs_filtered_out=dropped,
            notes=notes,
        )

    if resolved == "embedding":
        scorer: embedding.EmbeddingScorer | keyword.KeywordScorer = embedding.EmbeddingScorer(
            kept, model_name=embedding_model
        )
        explain = embedding.explain
    else:
        scorer = keyword.KeywordScorer(kept)
        explain = keyword.explain

    scored = scorer.score_all(resume)

    matches = [
        JobMatch(
            job=job,
            score=score,
            matched_skills=matched,
            missing_skills=missing,
            rationale=explain(score, matched, missing),
        )
        for job, (score, matched, missing) in zip(kept, scored)
        if score >= min_score
    ]
    matches.sort(key=lambda m: m.score, reverse=True)

    if not matches and scored:
        best = max(score for score, _, _ in scored)
        notes.append(
            f"No posting reached min_score={min_score:.2f}; the best was {best:.2f}. "
            "Lower min_score or broaden the search query."
        )
    if not resume.skills:
        notes.append(
            "No skills were detected in the resume, so ranking relies on wording alone. "
            "Check that the resume has a skills section."
        )

    return MatchResult(
        matches=matches[:top_k],
        strategy_used=resolved,  # type: ignore[arg-type]
        candidate_is_junior=junior,
        jobs_considered=len(jobs),
        jobs_filtered_out=dropped,
        notes=notes,
    )
