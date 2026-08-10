"""Ranking job postings against a parsed resume."""

from careercraft.core.matching.service import (
    DEFAULT_MIN_SCORE,
    available_strategies,
    default_strategy,
    rank_jobs,
)

__all__ = ["DEFAULT_MIN_SCORE", "available_strategies", "default_strategy", "rank_jobs"]
