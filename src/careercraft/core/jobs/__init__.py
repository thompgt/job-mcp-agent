"""Job posting sources."""

from careercraft.core.jobs.base import JobProvider, JobQuery
from careercraft.core.jobs.jobicy import JobicyProvider
from careercraft.core.jobs.mock import MockProvider

__all__ = ["JobProvider", "JobQuery", "JobicyProvider", "MockProvider"]
