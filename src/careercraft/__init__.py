"""CareerCraft — a local-first MCP server for the job hunt.

Parses resumes, fetches job postings, ranks them against a resume and drafts
cover letters. Everything runs on your machine; the only optional network
calls are to the job board and to a local Ollama daemon.
"""

from careercraft.errors import CareerCraftError, DependencyMissing, NotFound, ValidationFailed

__all__ = [
    "CareerCraftError",
    "DependencyMissing",
    "NotFound",
    "ValidationFailed",
    "__version__",
]

__version__ = "0.1.0"
