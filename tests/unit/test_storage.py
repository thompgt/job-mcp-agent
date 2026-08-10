"""The SQLite store."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import anyio

from careercraft.adapters.storage import SqliteStore
from careercraft.core.resume.parse import parse_resume_text
from careercraft.models import CoverLetter, Job


def _job(title: str = "Data Analyst", company: str = "Acme") -> Job:
    return Job(id=Job.make_id(title, company, title), title=title, company=company)


async def test_initialize_is_idempotent(settings):
    settings.ensure_dirs()
    store = SqliteStore(settings.db_path)
    await store.initialize()
    await store.initialize()
    assert await store.stats() == {"jobs": 0, "resumes": 0, "letters": 0, "saved_jobs": 0}


async def test_upsert_is_content_addressed(store):
    job = _job()
    await store.upsert_jobs([job])
    await store.upsert_jobs([job.model_copy(update={"description": "changed"})])
    assert (await store.stats())["jobs"] == 1
    assert (await store.get_job(job.id)).description == "changed"


async def test_get_job_returns_none_when_absent(store):
    assert await store.get_job("nope") is None


async def test_recent_jobs_is_newest_first(store):
    await store.upsert_jobs([_job("Older")])
    await store.upsert_jobs([_job("Newer")])
    titles = [j.title for j in await store.recent_jobs(10)]
    assert set(titles) == {"Older", "Newer"}


async def test_search_jobs_matches_title_and_company(store):
    await store.upsert_jobs([_job("Data Analyst", "Northwind"), _job("Pastry Chef", "Bakery")])
    assert {j.title for j in await store.search_jobs("analyst", 10)} == {"Data Analyst"}
    assert {j.title for j in await store.search_jobs("northwind", 10)} == {"Data Analyst"}


async def test_resume_round_trip_preserves_every_field(store, resume_text):
    resume = parse_resume_text(resume_text, source_name="synthetic.txt")
    resume.id = "r1"
    await store.save_resume(resume)
    back = await store.get_resume("r1")
    assert back is not None
    assert back.name == resume.name
    assert back.skills == resume.skills
    assert len(back.experience) == len(resume.experience)
    assert back.contacts.email == resume.contacts.email


async def test_latest_resume_returns_the_most_recent(store, resume_text):
    first = parse_resume_text(resume_text)
    first.id = "r1"
    await store.save_resume(first)
    await anyio.sleep(0.01)
    second = parse_resume_text(resume_text)
    second.id = "r2"
    await store.save_resume(second)
    latest = await store.latest_resume()
    assert latest is not None
    assert latest.id == "r2"


async def test_latest_resume_is_none_on_an_empty_store(store):
    assert await store.latest_resume() is None


async def test_list_and_delete_resumes(store, resume_text):
    resume = parse_resume_text(resume_text)
    resume.id = "r1"
    await store.save_resume(resume)
    summaries = await store.list_resumes(10)
    assert [s.id for s in summaries] == ["r1"]
    assert summaries[0].skills_count == len(resume.skills)

    assert await store.delete_resume("r1") is True
    assert await store.delete_resume("r1") is False
    assert await store.list_resumes(10) == []


async def test_letter_round_trip(store):
    letter = CoverLetter(job_id="j1", text="Dear team,", generated_by="template", word_count=2)
    await store.save_letter("L1", letter)
    back = await store.get_letter("L1")
    assert back is not None
    assert back.text == "Dear team,"
    assert await store.get_letter("nope") is None


async def test_saving_a_job_keeps_the_note(store):
    job = _job()
    await store.upsert_jobs([job])
    await store.save_job(job.id, "worth a shot")
    saved = await store.list_saved_jobs()
    assert [(j.id, note) for j, note in saved] == [(job.id, "worth a shot")]
    assert await store.unsave_job(job.id) is True
    assert await store.list_saved_jobs() == []


async def test_search_cache_respects_its_ttl(store):
    jobs = [_job("Cached Role")]
    await store.upsert_jobs(jobs)
    await store.cache_search("key1", jobs)

    hit = await store.cached_search("key1", 3600)
    assert hit is not None
    assert [j.title for j in hit] == ["Cached Role"]

    assert await store.cached_search("key1", 0) is None
    assert await store.cached_search("missing", 3600) is None


async def test_stats_counts_each_table(store, resume_text):
    resume = parse_resume_text(resume_text)
    resume.id = "r1"
    job = _job()
    await store.upsert_jobs([job])
    await store.save_resume(resume)
    await store.save_letter("L1", CoverLetter(job_id=job.id))
    await store.save_job(job.id)
    assert await store.stats() == {"jobs": 1, "resumes": 1, "letters": 1, "saved_jobs": 1}


# ------------------------------------------------------------- housekeeping


def _age_rows(store: SqliteStore, table: str, column: str, days: int) -> None:
    """Backdate every row so pruning has something old to find."""
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with sqlite3.connect(store.path) as conn:
        conn.execute(f"UPDATE {table} SET {column} = ?", (stamp,))


async def test_deleting_a_resume_takes_its_letters_with_it(store, resume_text):
    """A deleted resume used to leave letters quoting it behind."""
    resume = parse_resume_text(resume_text)
    resume.id = "r1"
    await store.save_resume(resume)
    await store.save_letter("L1", CoverLetter(job_id="j1", resume_id="r1", text="Dear team,"))
    await store.save_letter("L2", CoverLetter(job_id="j2", text="Unrelated letter"))

    assert await store.delete_resume("r1") is True
    assert await store.get_letter("L1") is None
    # A letter belonging to no resume is nobody's orphan.
    assert await store.get_letter("L2") is not None


async def test_deleting_a_missing_resume_deletes_nothing(store):
    await store.save_letter("L1", CoverLetter(job_id="j1", resume_id="r1"))
    assert await store.delete_resume("r-nope") is False
    assert await store.get_letter("L1") is not None


async def test_prune_drops_stale_postings(store):
    old, fresh = _job("Old Role"), _job("Fresh Role")
    await store.upsert_jobs([old])
    _age_rows(store, "jobs", "fetched_at", days=90)
    await store.upsert_jobs([fresh])

    result = await store.prune(max_age_days=30)

    assert result["jobs"] == 1
    assert [j.title for j in await store.recent_jobs()] == ["Fresh Role"]


async def test_prune_keeps_what_the_user_pointed_at(store):
    saved, lettered, plain = _job("Saved"), _job("Lettered"), _job("Plain")
    await store.upsert_jobs([saved, lettered, plain])
    await store.save_job(saved.id, "apply Monday")
    await store.save_letter("L1", CoverLetter(job_id=lettered.id))
    _age_rows(store, "jobs", "fetched_at", days=90)

    assert (await store.prune(max_age_days=30))["jobs"] == 1

    titles = {j.title for j in await store.recent_jobs()}
    assert titles == {"Saved", "Lettered"}


async def test_prune_does_not_hollow_out_a_live_cache_entry(store):
    """A cached search whose postings vanished would answer short."""
    jobs = [_job("Cached Role")]
    await store.upsert_jobs(jobs)
    await store.cache_search("key1", jobs)
    _age_rows(store, "jobs", "fetched_at", days=90)

    assert (await store.prune(max_age_days=30))["jobs"] == 0
    hit = await store.cached_search("key1", 3600)
    assert hit is not None and [j.title for j in hit] == ["Cached Role"]


async def test_prune_expires_old_cache_rows(store):
    jobs = [_job("Cached Role")]
    await store.upsert_jobs(jobs)
    await store.cache_search("key1", jobs)
    _age_rows(store, "search_cache", "created_at", days=90)

    assert (await store.prune(max_age_days=30))["search_cache"] == 1
    assert await store.cached_search("key1", 3600) is None


async def test_prune_sweeps_up_letters_orphaned_before_the_cascade(store):
    """Stores written before delete_resume cascaded still hold these."""
    await store.save_letter("L1", CoverLetter(job_id="j1", resume_id="gone"))

    assert (await store.prune(max_age_days=30))["orphaned_letters"] == 1
    assert await store.get_letter("L1") is None


async def test_prune_leaves_a_fresh_store_alone(store, resume_text):
    resume = parse_resume_text(resume_text)
    resume.id = "r1"
    await store.save_resume(resume)
    await store.upsert_jobs([_job()])
    await store.save_letter("L1", CoverLetter(job_id="j1", resume_id="r1"))

    assert await store.prune(max_age_days=30) == {
        "jobs": 0,
        "search_cache": 0,
        "orphaned_letters": 0,
    }
    assert await store.stats() == {"jobs": 1, "resumes": 1, "letters": 1, "saved_jobs": 0}
