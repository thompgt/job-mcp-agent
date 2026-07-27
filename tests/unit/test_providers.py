"""The two HTTP integrations, against recorded shapes.

Nothing here touches the network. The point of these tests is the *failure*
behaviour: v1 caught every exception and returned an empty list, which made
"the API is down" indistinguishable from "no jobs matched" — the calling model
would then confidently report that no such roles exist.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from careercraft.adapters.llm import NullProvider, OllamaProvider, get_provider
from careercraft.core.jobs import JobicyProvider, JobQuery, MockProvider
from careercraft.errors import ProviderError

BASE = "https://jobicy.test/api/v2/remote-jobs"
OLLAMA = "http://ollama.test:11434"

PAYLOAD = {
    "jobCount": 2,
    "jobs": [
        {
            "id": 1,
            "jobTitle": "Data Analyst",
            "companyName": "Northwind",
            "jobGeo": "USA",
            "jobLevel": ["Any"],
            "jobType": ["full-time"],
            "jobDescription": "<p>Work with <b>Python</b> &amp; SQL.</p>",
            "url": "https://jobicy.test/jobs/1",
            "pubDate": "2026-01-05 10:00:00",
            "annualSalaryMin": 70000,
            "annualSalaryMax": 90000,
            "salaryCurrency": "USD",
        },
        {
            "id": 2,
            "jobTitle": "Backend Engineer",
            "companyName": "Helios",
            "jobLevel": "Senior",
            "jobType": "full-time",
            "jobExcerpt": "Go and Kubernetes.",
            "url": "https://jobicy.test/jobs/2",
        },
    ],
}


# ------------------------------------------------------------- jobicy


@respx.mock
async def test_normalizes_a_realistic_payload():
    respx.get(BASE).mock(return_value=httpx.Response(200, json=PAYLOAD))
    jobs = await JobicyProvider(base_url=BASE).search(JobQuery(query="data"))

    assert [j.title for j in jobs] == ["Data Analyst", "Backend Engineer"]
    first = jobs[0]
    assert first.company == "Northwind"
    assert first.description == "Work with Python & SQL."  # HTML stripped, entities decoded
    assert first.level == "Any"  # list flattened
    assert first.salary == "70000-90000 USD"
    assert first.published_at is not None
    assert first.source == "jobicy"


@respx.mock
async def test_ids_are_stable_across_refetches():
    respx.get(BASE).mock(return_value=httpx.Response(200, json=PAYLOAD))
    first = await JobicyProvider(base_url=BASE).search(JobQuery())
    second = await JobicyProvider(base_url=BASE).search(JobQuery())
    assert [j.id for j in first] == [j.id for j in second]


@respx.mock
async def test_an_upstream_field_change_does_not_remint_the_id():
    """The id hashes title/company/url only, not the whole payload."""
    respx.get(BASE).mock(return_value=httpx.Response(200, json=PAYLOAD))
    before = (await JobicyProvider(base_url=BASE).search(JobQuery()))[0].id

    tweaked = {"jobs": [{**PAYLOAD["jobs"][0], "jobDescription": "totally rewritten"}]}
    respx.get(BASE).mock(return_value=httpx.Response(200, json=tweaked))
    after = (await JobicyProvider(base_url=BASE).search(JobQuery()))[0].id
    assert before == after


@respx.mock
async def test_count_is_clamped_to_the_accepted_range():
    route = respx.get(BASE).mock(return_value=httpx.Response(200, json={"jobs": []}))
    await JobicyProvider(base_url=BASE).search(JobQuery(limit=5000))
    assert route.calls.last.request.url.params["count"] == "50"


@respx.mock
async def test_untitled_entries_are_dropped_not_fabricated():
    respx.get(BASE).mock(
        return_value=httpx.Response(200, json={"jobs": [{"companyName": "Ghost Inc"}, "junk"]})
    )
    assert await JobicyProvider(base_url=BASE).search(JobQuery()) == []


@respx.mock
async def test_an_unexpected_response_shape_still_finds_the_list():
    respx.get(BASE).mock(
        return_value=httpx.Response(200, json={"payload": {"x": 1}, "results": PAYLOAD["jobs"]})
    )
    assert len(await JobicyProvider(base_url=BASE).search(JobQuery())) == 2


@respx.mock
async def test_an_http_error_raises_rather_than_returning_nothing():
    respx.get(BASE).mock(return_value=httpx.Response(503))
    with pytest.raises(ProviderError) as excinfo:
        await JobicyProvider(base_url=BASE).search(JobQuery())
    assert "503" in str(excinfo.value)


@respx.mock
async def test_a_connection_failure_names_the_offline_workaround():
    respx.get(BASE).mock(side_effect=httpx.ConnectError("no route to host"))
    with pytest.raises(ProviderError) as excinfo:
        await JobicyProvider(base_url=BASE).search(JobQuery())
    assert "mock" in str(excinfo.value)


@respx.mock
async def test_a_non_json_body_raises():
    respx.get(BASE).mock(return_value=httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(ProviderError):
        await JobicyProvider(base_url=BASE).search(JobQuery())


# --------------------------------------------------------------- mock


async def test_the_mock_provider_needs_no_network():
    jobs = await MockProvider().search(JobQuery(limit=10))
    assert jobs
    assert all(j.source == "mock" for j in jobs)
    assert len({j.id for j in jobs}) == len(jobs)


async def test_the_mock_provider_filters_by_query():
    hits = await MockProvider().search(JobQuery(query="data"))
    assert hits
    assert all("data" in (j.title + j.description).lower() for j in hits)


async def test_the_mock_provider_spans_seniority_levels():
    """Filter tests need something to filter."""
    titles = " ".join(j.title.lower() for j in await MockProvider().search(JobQuery(limit=50)))
    assert "junior" in titles
    assert "senior" in titles or "principal" in titles


# ------------------------------------------------------------- ollama


@respx.mock
async def test_is_available_is_true_when_the_daemon_answers():
    respx.get(f"{OLLAMA}/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3.2:1b"}]})
    )
    assert await OllamaProvider(base_url=OLLAMA, model="llama3.2:1b").is_available() is True


@respx.mock
async def test_is_available_never_raises():
    respx.get(f"{OLLAMA}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    assert await OllamaProvider(base_url=OLLAMA, model="llama3.2:1b").is_available() is False


@respx.mock
async def test_complete_returns_the_message_content():
    respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=httpx.Response(
            200, json={"message": {"role": "assistant", "content": "Dear Hiring Manager,"}}
        )
    )
    provider = OllamaProvider(base_url=OLLAMA, model="llama3.2:1b")
    out = await provider.complete([{"role": "user", "content": "write"}])
    assert out == "Dear Hiring Manager,"


@respx.mock
async def test_a_missing_model_says_so_and_names_the_pull():
    respx.post(f"{OLLAMA}/api/chat").mock(return_value=httpx.Response(404, json={"error": "x"}))
    provider = OllamaProvider(base_url=OLLAMA, model="mistral:7b")
    with pytest.raises(ProviderError) as excinfo:
        await provider.complete([{"role": "user", "content": "hi"}])
    assert "mistral:7b" in str(excinfo.value)
    assert "ollama pull" in str(excinfo.value)


@respx.mock
async def test_an_unreachable_daemon_names_ollama_serve():
    respx.post(f"{OLLAMA}/api/chat").mock(side_effect=httpx.ConnectError("refused"))
    provider = OllamaProvider(base_url=OLLAMA, model="llama3.2:1b")
    with pytest.raises(ProviderError) as excinfo:
        await provider.complete([{"role": "user", "content": "hi"}])
    assert "ollama serve" in str(excinfo.value)


@respx.mock
async def test_list_models_returns_names():
    respx.get(f"{OLLAMA}/api/tags").mock(
        return_value=httpx.Response(
            200, json={"models": [{"name": "llama3.2:1b"}, {"name": "qwen2.5:3b"}]}
        )
    )
    names = await OllamaProvider(base_url=OLLAMA, model="llama3.2:1b").list_models()
    assert names == ["llama3.2:1b", "qwen2.5:3b"]


# ---------------------------------------------------------------- null


async def test_the_null_provider_is_honest_about_being_absent():
    provider = NullProvider()
    assert await provider.is_available() is False
    with pytest.raises(ProviderError) as excinfo:
        await provider.complete([{"role": "user", "content": "hi"}])
    assert "ollama" in str(excinfo.value).lower()


def test_get_provider_resolves_by_name():
    assert isinstance(get_provider("ollama"), OllamaProvider)
    assert isinstance(get_provider("null"), NullProvider)
