"""Offline provider.

Exists so the whole pipeline is demonstrable and testable with no network:
tests use it, and ``source="mock"`` lets a user try the server on a plane. The
postings are deliberately varied in seniority, degree requirement and tech
stack so the matching heuristics have something real to bite on — v1's mock
emitted N copies of "Software Engineer {i}", which could not exercise any of
the ranking logic.
"""

from __future__ import annotations

from careercraft.core.jobs.base import JobProvider, JobQuery
from careercraft.models import Job

_TEMPLATES: list[dict[str, str]] = [
    {
        "title": "Junior Data Analyst",
        "company": "Northwind Analytics",
        "level": "Entry-level",
        "description": (
            "Work with the analytics team to build dashboards and reports. You will write "
            "SQL against our Postgres warehouse, use Python and pandas for ad-hoc analysis, "
            "and present findings in Tableau. Bachelor's degree preferred."
        ),
    },
    {
        "title": "Software Engineer, Backend",
        "company": "Lumen Systems",
        "level": "Mid-level",
        "description": (
            "Build and operate REST APIs in Python with FastAPI, backed by PostgreSQL and "
            "Redis. Services run on Kubernetes with CI/CD through GitHub Actions. We care "
            "about unit testing and clear documentation."
        ),
    },
    {
        "title": "Senior Machine Learning Engineer",
        "company": "Halcyon AI",
        "level": "Senior",
        "description": (
            "Lead the design of production ML systems. Deep experience with PyTorch, "
            "distributed training and MLOps required. A Master's degree or PhD in a "
            "quantitative field is expected."
        ),
    },
    {
        "title": "Data Engineer",
        "company": "Meridian Data",
        "level": "Mid-level",
        "description": (
            "Own our data pipelines: Airflow orchestration, Spark transformations, dbt "
            "models landing in Snowflake. Strong SQL and Python required, AWS experience "
            "a plus."
        ),
    },
    {
        "title": "Frontend Engineer",
        "company": "Vireo Labs",
        "level": "Mid-level",
        "description": (
            "Build our customer-facing app in React and TypeScript with Next.js and "
            "Tailwind CSS. You will work closely with design and own accessibility."
        ),
    },
    {
        "title": "Quantitative Research Intern",
        "company": "Ashford Capital",
        "level": "Internship",
        "description": (
            "Summer internship on the systematic research desk. Python, statistics and "
            "econometrics. Exposure to Bloomberg and risk management workflows."
        ),
    },
    {
        "title": "DevOps Engineer",
        "company": "Stackline Cloud",
        "level": "Mid-level",
        "description": (
            "Terraform-managed AWS infrastructure, Docker and Kubernetes workloads, "
            "observability and on-call. Linux fundamentals and Bash scripting essential."
        ),
    },
    {
        "title": "Principal Systems Architect",
        "company": "Corvus Enterprise",
        "level": "Principal",
        "description": (
            "Set technical direction for distributed systems handling millions of "
            "requests. Fifteen years of experience and a track record of system design "
            "leadership required."
        ),
    },
]


class MockProvider(JobProvider):
    name = "mock"

    async def search(self, query: JobQuery) -> list[Job]:
        needle = query.query.lower().strip()
        jobs: list[Job] = []
        for index, template in enumerate(_TEMPLATES):
            haystack = f"{template['title']} {template['description']}".lower()
            if needle and needle not in haystack:
                continue
            url = f"https://example.invalid/jobs/{index}"
            jobs.append(
                Job(
                    id=Job.make_id(template["title"], template["company"], url),
                    title=template["title"],
                    company=template["company"],
                    location=query.location or "Remote",
                    description=template["description"],
                    url=url,
                    source="mock",
                    level=template["level"],
                    job_type="Full-time",
                )
            )
        return jobs[: query.limit]
