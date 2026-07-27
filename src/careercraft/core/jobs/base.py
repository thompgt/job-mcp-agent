"""The job provider contract.

One narrow interface so a second board can be added without touching the MCP
layer, the API or the matcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from careercraft.models import Job


@dataclass(slots=True, frozen=True)
class JobQuery:
    """A normalised search request.

    Providers are expected to honour what they can and ignore the rest —
    filtering the remainder is the caller's job, because a provider that
    silently returns nothing is worse than one that over-returns.
    """

    query: str = ""
    location: str = ""
    limit: int = 25
    remote_only: bool = True


@runtime_checkable
class JobProvider(Protocol):
    """A source of job postings."""

    name: str

    async def search(self, query: JobQuery) -> list[Job]:
        """Return postings for ``query``.

        Raises :class:`careercraft.errors.ProviderError` when the upstream
        service is unreachable or returns something unusable. Providers must
        not swallow failures into an empty list — v1 did, which made "the API
        is down" and "there are no remote Python jobs" indistinguishable.
        """
        ...
