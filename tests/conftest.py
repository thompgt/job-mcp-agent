"""Shared fixtures.

Every test gets its own data directory and its own SQLite file, and no test
touches the network: the job provider is the in-process mock and the language
model is the null provider. The two integration points that do speak HTTP —
Jobicy and Ollama — are tested against ``respx`` mocks in ``tests/unit``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from careercraft.adapters.llm import NullProvider
from careercraft.adapters.storage import SqliteStore
from careercraft.core.jobs import MockProvider
from careercraft.service import CareerCraftService
from careercraft.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the retry backoff out of the test clock.

    ``careercraft.retry`` sleeps between attempts on purpose; making the suite
    wait for it would add seconds per transient-failure test and buy nothing.
    The number of attempts is what the tests assert on, so only the sleep is
    stubbed out.
    """

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("careercraft.retry.sleep", instant)


@pytest.fixture
def resume_text() -> str:
    return (FIXTURES / "synthetic_resume.txt").read_text(encoding="utf-8")


@pytest.fixture
def senior_resume_text() -> str:
    return (FIXTURES / "synthetic_senior_resume.txt").read_text(encoding="utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointed entirely at a temp directory.

    ``ollama_base_url="disabled"`` is what :func:`build_service` reads to wire
    in the null provider, but tests construct the service directly anyway.
    """
    return Settings(
        data_dir=tmp_path / "data",
        allowed_paths=[tmp_path],
        ollama_base_url="disabled",
        transport="stdio",
    )


@pytest.fixture
async def store(settings: Settings) -> SqliteStore:
    settings.ensure_dirs()
    s = SqliteStore(settings.db_path)
    await s.initialize()
    return s


@pytest.fixture
async def service(settings: Settings, store: SqliteStore) -> CareerCraftService:
    svc = CareerCraftService(
        settings,
        store=store,
        job_provider=MockProvider(),
        llm=NullProvider(),
    )
    await svc.startup()
    return svc
