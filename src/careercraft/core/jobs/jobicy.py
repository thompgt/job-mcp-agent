"""Jobicy remote-jobs provider.

Jobicy is free, needs no API key and only lists remote roles — which is why it
is the default source. It is also the reason ``remote_only`` defaults to True:
there is nothing else on offer here.
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

import httpx

from careercraft.core.jobs.base import JobProvider, JobQuery
from careercraft.errors import ProviderError
from careercraft.models import Job

_TAG_RE = re.compile(r"<[^>]+>")
#: Jobicy rejects counts outside this range with a 400.
_MIN_COUNT, _MAX_COUNT = 1, 50


def _strip_html(raw: str) -> str:
    """Job descriptions arrive as HTML; matching wants prose."""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _first_list(payload: Any) -> list[Any]:
    """Pull the postings array out of a response whose shape has drifted before."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("jobs", "data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        lists = [v for v in payload.values() if isinstance(v, list)]
        if lists:
            return max(lists, key=len)
    return []


class JobicyProvider(JobProvider):
    name = "jobicy"

    def __init__(
        self,
        *,
        base_url: str = "https://jobicy.com/api/v2/remote-jobs",
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._client = client
        self._owned: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Reuse one client for the provider's lifetime.

        Constructing an ``AsyncClient`` loads a TLS trust store, which costs
        the better part of a second on Windows. Per-search construction made
        every job search pay it, and it is the provider's own connection pool
        that we want to keep warm anyway.
        """
        if self._client is not None:
            return self._client
        if self._owned is None or self._owned.is_closed:
            self._owned = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "careercraft-mcp"},
            )
        return self._owned

    async def aclose(self) -> None:
        if self._owned is not None and not self._owned.is_closed:
            await self._owned.aclose()
        self._owned = None

    async def search(self, query: JobQuery) -> list[Job]:
        params: dict[str, Any] = {"count": max(_MIN_COUNT, min(_MAX_COUNT, query.limit))}
        if query.query:
            params["tag"] = query.query
        if query.location:
            params["geo"] = query.location.lower().replace(" ", "-")

        try:
            response = await self._get_client().get(self._base_url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"Jobicy returned HTTP {exc.response.status_code}.",
                remedy="Try a broader query, or retry in a minute if this is rate limiting.",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Could not reach Jobicy: {exc}.",
                remedy="Check network access, or pass source='mock' to work offline.",
            ) from exc
        except ValueError as exc:
            raise ProviderError(
                "Jobicy returned a response that is not JSON.",
                remedy="This is usually a transient upstream error; retry shortly.",
            ) from exc

        return [job for raw in _first_list(payload) if (job := self._normalize(raw)) is not None]

    @staticmethod
    def _normalize(raw: Any) -> Job | None:
        if not isinstance(raw, dict):
            return None
        title = str(raw.get("jobTitle") or raw.get("title") or "").strip()
        if not title:
            return None

        company = str(raw.get("companyName") or raw.get("company") or "").strip()
        url = str(raw.get("url") or raw.get("jobUrl") or "").strip()
        description = _strip_html(
            str(raw.get("jobDescription") or raw.get("jobExcerpt") or raw.get("description") or "")
        )

        level = raw.get("jobLevel") or ""
        job_type = raw.get("jobType") or ""
        # Both fields arrive as either a string or a one-element list.
        if isinstance(level, list):
            level = ", ".join(str(x) for x in level)
        if isinstance(job_type, list):
            job_type = ", ".join(str(x) for x in job_type)

        salary_min = raw.get("annualSalaryMin")
        salary_max = raw.get("annualSalaryMax")
        currency = raw.get("salaryCurrency") or ""
        salary = (
            f"{salary_min}-{salary_max} {currency}".strip() if salary_min and salary_max else ""
        )

        return Job(
            id=Job.make_id(title, company, url),
            title=title,
            company=company,
            location=str(raw.get("jobGeo") or raw.get("location") or "Remote").strip(),
            description=description,
            url=url,
            source="jobicy",
            level=str(level),
            job_type=str(job_type),
            salary=salary,
            published_at=_parse_date(raw.get("pubDate")),
        )
