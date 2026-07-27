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


class _StderrProxy:
    """A file object that resolves ``sys.stderr`` on every write.

    Binding the logger to the ``sys.stderr`` object that happened to exist at
    configuration time is a subtle trap: anything that later replaces the
    stream — a test harness capturing output, a supervisor reopening the log,
    ``contextlib.redirect_stderr`` — leaves the logger holding a closed file,
    and the next log call raises ``ValueError: I/O operation on closed file``
    from inside unrelated code. Resolving late costs one attribute lookup.
    """

    def write(self, data: str) -> int:
        return sys.stderr.write(data)

    def flush(self) -> None:
        sys.stderr.flush()

    def isatty(self) -> bool:
        return bool(getattr(sys.stderr, "isatty", lambda: False)())


def configure_logging(level: str = "INFO", *, force_json: bool | None = None) -> None:
    """Install the structlog + stdlib logging pipeline. Idempotent."""
    global _configured
    if _configured:
        return

    stderr = _StderrProxy()
    numeric = getattr(logging, level.upper(), logging.INFO)
    as_json = (not stderr.isatty()) if force_json is None else force_json

    handler = logging.StreamHandler(stderr)
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
        processors += [structlog.dev.ConsoleRenderer(colors=stderr.isatty())]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric),
        logger_factory=structlog.WriteLoggerFactory(file=stderr),  # type: ignore[arg-type]
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger. Safe to call at import time."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
