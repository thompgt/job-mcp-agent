"""Retrying the two calls that leave this process.

Both network dependencies — the job board and the Ollama daemon — used to get
exactly one attempt. A single dropped connection or a momentary 503 therefore
surfaced as a hard ``ProviderError``: a job search that returned nothing, or a
cover letter that failed, when trying again a second later would have worked.

What is retried is deliberately narrow. Transport failures and the status
codes that *mean* "later" (429, 502, 503, 504) are worth another attempt; a
400 or a 404 is not, because nothing about waiting makes a malformed query
valid or a missing model present. Anything the predicate does not recognise
propagates untouched on the first attempt, so the callers' error mapping is
unchanged.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from anyio import sleep

from careercraft.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")

#: Status codes that describe a transient condition rather than a bad request.
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})

#: Three attempts total, so two retries. Enough to ride out a blip; few enough
#: that a genuinely dead dependency still fails inside a tool call's patience.
DEFAULT_ATTEMPTS = 3

#: First backoff, doubled each time: 0.5s, then 1.0s. Full jitter on top, so a
#: burst of concurrent searches does not retry in lockstep.
DEFAULT_BACKOFF = 0.5


def is_transient(exc: BaseException) -> bool:
    """Whether another attempt could plausibly succeed."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    # TransportError covers connect, read, write, pool and timeout failures.
    return isinstance(exc, httpx.TransportError)


async def with_retry(
    call: Callable[[], Awaitable[T]],
    *,
    what: str,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: float = DEFAULT_BACKOFF,
    retry_on: Callable[[BaseException], bool] = is_transient,
) -> T:
    """Await ``call()``, retrying transient failures with jittered backoff.

    ``call`` must be a zero-argument coroutine function, not a coroutine: a
    coroutine can only be awaited once, and the whole point here is to run it
    again.

    The exception from the final attempt is re-raised as-is, so callers keep
    mapping ``httpx`` errors to their own ``ProviderError`` messages exactly as
    they did when there was only ever one attempt.
    """
    last: BaseException
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except Exception as exc:
            if attempt >= attempts or not retry_on(exc):
                raise
            last = exc
            # Full jitter: sleep somewhere in [0, delay], which spreads a herd
            # of simultaneous retries instead of synchronising them.
            delay = backoff * 2 ** (attempt - 1)
            wait = random.random() * delay  # noqa: S311 - jitter, not a secret
            log.warning(
                "retrying",
                what=what,
                attempt=attempt,
                of=attempts,
                wait=round(wait, 3),
                error=str(last),
            )
            await sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover
