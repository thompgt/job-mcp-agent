"""Logging setup.

**Every handler writes to stderr.** In stdio transport, stdout carries the
JSON-RPC frame stream; a single stray ``print`` there corrupts the session and
the host disconnects with a parse error that looks like a server crash. This
module is the one place that decides where log bytes go, and the answer is
always stderr.

Output is human-readable when stderr is a TTY and JSON otherwise, so
``docker logs`` and MCP host logs stay machine-parseable.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_configured = False


def configure_logging(level: str = "INFO", *, force_json: bool | None = None) -> None:
    """Install the structlog + stdlib logging pipeline. Idempotent."""
    global _configured
    if _configured:
        return

    numeric = getattr(logging, level.upper(), logging.INFO)
    as_json = (not sys.stderr.isatty()) if force_json is None else force_json

    handler = logging.StreamHandler(sys.stderr)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(numeric)

    # These are chatty at INFO and say nothing a user of this server needs.
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "asyncio"):
        logging.getLogger(noisy).setLevel(max(numeric, logging.WARNING))

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if as_json:
        processors += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        processors += [structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Safe to call at import time."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
