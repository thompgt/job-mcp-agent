"""The retry helper, and the two providers that use it.

The behaviour worth pinning down is the *boundary*: what counts as transient
and what does not. Retrying a 400 wastes a user's time on a request that can
never succeed; not retrying a 503 turns a blip into a failed job search.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from careercraft.adapters.llm import OllamaProvider
from careercraft.core.jobs import JobicyProvider, JobQuery
from careercraft.errors import ProviderError
from careercraft.retry import with_retry

BASE = "https://jobicy.test/api/v2/remote-jobs"
OLLAMA = "http://ollama.test:11434"


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    return httpx.HTTPStatusError(
        f"{code}", request=request, response=httpx.Response(code, request=request)
    )


# ---------------------------------------------------------------- the helper


async def test_a_transient_failure_is_retried_and_can_succeed():
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("boom")
        return "ok"

    assert await with_retry(flaky, what="test") == "ok"
    assert calls == 3


async def test_attempts_are_bounded_and_the_last_error_propagates():
    calls = 0

    async def always_down() -> str:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("down")

    with pytest.raises(httpx.ConnectTimeout):
        await with_retry(always_down, what="test", attempts=3)
    assert calls == 3


@pytest.mark.parametrize("code", [429, 502, 503, 504])
async def test_transient_status_codes_are_retried(code: int):
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        raise _status_error(code)

    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(flaky, what="test", attempts=2)
    assert calls == 2


@pytest.mark.parametrize("code", [400, 401, 404, 422, 500])
async def test_a_permanent_status_code_is_not_retried(code: int):
    calls = 0

    async def rejected() -> str:
        nonlocal calls
        calls += 1
        raise _status_error(code)

    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(rejected, what="test")
    assert calls == 1


async def test_an_unrelated_exception_is_not_retried():
    calls = 0

    async def broken() -> str:
        nonlocal calls
        calls += 1
        raise ValueError("not a network problem")

    with pytest.raises(ValueError):
        await with_retry(broken, what="test")
    assert calls == 1


# ---------------------------------------------------------------- providers


@respx.mock
async def test_jobicy_recovers_from_a_dropped_connection():
    route = respx.get(BASE).mock(
        side_effect=[
            httpx.ConnectError("dropped"),
            httpx.Response(200, json={"jobs": [{"jobTitle": "Analyst", "companyName": "N"}]}),
        ]
    )
    jobs = await JobicyProvider(base_url=BASE).search(JobQuery(query="data"))

    assert [j.title for j in jobs] == ["Analyst"]
    assert route.call_count == 2


@respx.mock
async def test_jobicy_gives_up_and_still_reports_the_status():
    route = respx.get(BASE).mock(return_value=httpx.Response(503))
    with pytest.raises(ProviderError) as excinfo:
        await JobicyProvider(base_url=BASE).search(JobQuery())

    assert "503" in str(excinfo.value)
    assert route.call_count == 3


@respx.mock
async def test_jobicy_does_not_retry_a_rejected_query():
    route = respx.get(BASE).mock(return_value=httpx.Response(400))
    with pytest.raises(ProviderError):
        await JobicyProvider(base_url=BASE).search(JobQuery())

    assert route.call_count == 1


@respx.mock
async def test_ollama_retries_generation():
    route = respx.post(f"{OLLAMA}/api/chat").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"message": {"content": "Dear hiring manager"}}),
        ]
    )
    provider = OllamaProvider(base_url=OLLAMA, model="llama3.2:1b")
    text = await provider.complete([{"role": "user", "content": "hi"}])

    assert text == "Dear hiring manager"
    assert route.call_count == 2


@respx.mock
async def test_ollama_does_not_retry_a_missing_model():
    route = respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(404))
    provider = OllamaProvider(base_url=OLLAMA, model="nope")
    with pytest.raises(ProviderError) as excinfo:
        await provider.complete([{"role": "user", "content": "hi"}])

    assert "ollama pull" in str(excinfo.value)
    assert route.call_count == 1


@respx.mock
async def test_the_availability_probe_stays_single_shot():
    route = respx.get(f"{OLLAMA}/api/tags").mock(return_value=httpx.Response(503))
    assert await OllamaProvider(base_url=OLLAMA).daemon_reachable() is False
    assert route.call_count == 1
