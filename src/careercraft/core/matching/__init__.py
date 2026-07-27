"""Ranking job postings against a parsed resume."""

from careercraft.core.matching.service import (
    available_strategies,
    default_strategy,
    rank_jobs,
)

__all__ = ["available_strategies", "default_strategy", "rank_jobs"]
