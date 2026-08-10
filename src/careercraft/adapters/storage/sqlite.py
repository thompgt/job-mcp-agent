"""SQLite persistence.

v1 stored jobs in MongoDB as ``{source_hash, payload}`` — a key-value blob
store, i.e. one table — which meant every user had to run a database server to
try the project. SQLite in the platform data directory needs nothing, and the
whole store is one file the user can delete.

The stdlib ``sqlite3`` driver is synchronous, so every public method here is
async and dispatches to a worker thread. Schema changes go through
``PRAGMA user_version``; at this size that is a great deal less machinery than
Alembic for the same guarantee.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import anyio.to_thread

from careercraft.logging import get_logger
from careercraft.models import CoverLetter, Job, ParsedResume, ResumeSummary

log = get_logger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    payload     TEXT NOT NULL,
    fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_fetched_at ON jobs (fetched_at DESC);

CREATE TABLE IF NOT EXISTS resumes (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    source_name TEXT,
    payload     TEXT NOT NULL,
    parsed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS resumes_parsed_at ON resumes (parsed_at DESC);

CREATE TABLE IF NOT EXISTS letters (
    id         TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL,
    resume_id  TEXT,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_jobs (
    job_id   TEXT PRIMARY KEY,
    note     TEXT NOT NULL DEFAULT '',
    saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_cache (
    cache_key  TEXT PRIMARY KEY,
    job_ids    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    """Async facade over a single SQLite file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._ready = False

    # ----------------------------------------------------------- plumbing

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # WAL lets the API read while the MCP server writes; without it the
        # two processes serialise on every statement.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _migrate_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version < SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                log.info("storage.migrated", from_version=version, to=SCHEMA_VERSION)

    async def initialize(self) -> None:
        """Create the file and apply the schema. Safe to call repeatedly."""
        if self._ready:
            return
        await anyio.to_thread.run_sync(self._migrate_sync)
        self._ready = True

    async def _run(self, fn: Any, *args: Any) -> Any:
        await self.initialize()
        return await anyio.to_thread.run_sync(fn, *args)

    # --------------------------------------------------------------- jobs

    def _upsert_jobs_sync(self, jobs: list[Job]) -> int:
        now = _utcnow_iso()
        rows = [
            (job.id, job.title, job.company, job.source, job.model_dump_json(), now) for job in jobs
        ]
        with self._connect() as conn:
            # Postings are content-addressed, so a re-fetch of the same role is
            # an update rather than a duplicate.
            conn.executemany(
                "INSERT INTO jobs (id, title, company, source, payload, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, "
                "fetched_at=excluded.fetched_at",
                rows,
            )
        return len(rows)

    async def upsert_jobs(self, jobs: Iterable[Job]) -> int:
        batch = list(jobs)
        if not batch:
            return 0
        return int(await self._run(self._upsert_jobs_sync, batch))

    def _get_job_sync(self, job_id: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.model_validate_json(row["payload"]) if row else None

    async def get_job(self, job_id: str) -> Job | None:
        result = await self._run(self._get_job_sync, job_id)
        return result  # type: ignore[no-any-return]

    def _recent_jobs_sync(self, limit: int) -> list[Job]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM jobs ORDER BY fetched_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Job.model_validate_json(row["payload"]) for row in rows]

    async def recent_jobs(self, limit: int = 50) -> list[Job]:
        return list(await self._run(self._recent_jobs_sync, limit))

    def _search_jobs_sync(self, needle: str, limit: int) -> list[Job]:
        pattern = f"%{needle.lower()}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM jobs WHERE lower(title) LIKE ? OR lower(company) LIKE ? "
                "ORDER BY fetched_at DESC LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        return [Job.model_validate_json(row["payload"]) for row in rows]

    async def search_jobs(self, needle: str, limit: int = 50) -> list[Job]:
        return list(await self._run(self._search_jobs_sync, needle, limit))

    # ------------------------------------------------------------ resumes

    def _save_resume_sync(self, resume: ParsedResume) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO resumes (id, name, source_name, payload, parsed_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, "
                "parsed_at=excluded.parsed_at",
                (
                    resume.id,
                    resume.name,
                    resume.source_name,
                    resume.model_dump_json(),
                    resume.parsed_at.isoformat(),
                ),
            )
        return resume.id

    async def save_resume(self, resume: ParsedResume) -> str:
        return str(await self._run(self._save_resume_sync, resume))

    def _get_resume_sync(self, resume_id: str) -> ParsedResume | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        return ParsedResume.model_validate_json(row["payload"]) if row else None

    async def get_resume(self, resume_id: str) -> ParsedResume | None:
        result = await self._run(self._get_resume_sync, resume_id)
        return result  # type: ignore[no-any-return]

    def _latest_resume_sync(self) -> ParsedResume | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM resumes ORDER BY parsed_at DESC LIMIT 1"
            ).fetchone()
        return ParsedResume.model_validate_json(row["payload"]) if row else None

    async def latest_resume(self) -> ParsedResume | None:
        """The most recently parsed resume.

        Lets every tool take an optional ``resume_id`` and still do the right
        thing in a conversation where the user parsed one resume and then said
        "now match me against these jobs".
        """
        result = await self._run(self._latest_resume_sync)
        return result  # type: ignore[no-any-return]

    def _list_resumes_sync(self, limit: int) -> list[ResumeSummary]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM resumes ORDER BY parsed_at DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for row in rows:
            resume = ParsedResume.model_validate_json(row["payload"])
            out.append(
                ResumeSummary(
                    id=resume.id,
                    name=resume.name,
                    source_name=resume.source_name,
                    skills_count=len(resume.skills),
                    experience_count=len(resume.experience),
                    parsed_at=resume.parsed_at,
                )
            )
        return out

    async def list_resumes(self, limit: int = 20) -> list[ResumeSummary]:
        return list(await self._run(self._list_resumes_sync, limit))

    def _delete_resume_sync(self, resume_id: str) -> bool:
        with self._connect() as conn:
            # The letters go with it. Deleting only the resume row left every
            # letter generated from it pointing at a resume_id that resolves to
            # nothing — and those letters quote the resume, so "delete my
            # resume" would have left the contents of it in the store. The
            # cascade is written out rather than declared as a foreign key
            # because letters.resume_id was created without one and adding it
            # to an existing table means rebuilding it.
            cursor = conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                letters = conn.execute(
                    "DELETE FROM letters WHERE resume_id = ?", (resume_id,)
                ).rowcount
                if letters:
                    log.info("storage.letters_deleted", resume_id=resume_id, count=letters)
        return deleted

    async def delete_resume(self, resume_id: str) -> bool:
        return bool(await self._run(self._delete_resume_sync, resume_id))

    # ------------------------------------------------------------ letters

    def _save_letter_sync(self, letter_id: str, letter: CoverLetter) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO letters (id, job_id, resume_id, payload, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    letter_id,
                    letter.job_id,
                    letter.resume_id,
                    letter.model_dump_json(),
                    letter.created_at.isoformat(),
                ),
            )
        return letter_id

    async def save_letter(self, letter_id: str, letter: CoverLetter) -> str:
        return str(await self._run(self._save_letter_sync, letter_id, letter))

    def _get_letter_sync(self, letter_id: str) -> CoverLetter | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM letters WHERE id = ?", (letter_id,)).fetchone()
        return CoverLetter.model_validate_json(row["payload"]) if row else None

    async def get_letter(self, letter_id: str) -> CoverLetter | None:
        result = await self._run(self._get_letter_sync, letter_id)
        return result  # type: ignore[no-any-return]

    # -------------------------------------------------------- saved  jobs

    def _save_job_sync(self, job_id: str, note: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO saved_jobs (job_id, note, saved_at) VALUES (?, ?, ?)",
                (job_id, note, _utcnow_iso()),
            )

    async def save_job(self, job_id: str, note: str = "") -> None:
        await self._run(self._save_job_sync, job_id, note)

    def _list_saved_sync(self) -> list[tuple[Job, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT j.payload AS payload, s.note AS note FROM saved_jobs s "
                "JOIN jobs j ON j.id = s.job_id ORDER BY s.saved_at DESC"
            ).fetchall()
        return [(Job.model_validate_json(r["payload"]), r["note"]) for r in rows]

    async def list_saved_jobs(self) -> list[tuple[Job, str]]:
        return list(await self._run(self._list_saved_sync))

    def _unsave_job_sync(self, job_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM saved_jobs WHERE job_id = ?", (job_id,))
        return cursor.rowcount > 0

    async def unsave_job(self, job_id: str) -> bool:
        return bool(await self._run(self._unsave_job_sync, job_id))

    # ------------------------------------------------------- search cache

    def _cache_get_sync(self, key: str, ttl_seconds: int) -> list[Job] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT job_ids, created_at FROM search_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])
            ).total_seconds()
            if age > ttl_seconds:
                return None
            ids = json.loads(row["job_ids"])
            if not ids:
                return []
            placeholders = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT id, payload FROM jobs WHERE id IN ({placeholders})",  # noqa: S608
                ids,
            ).fetchall()
        by_id = {r["id"]: Job.model_validate_json(r["payload"]) for r in rows}
        # Preserve the ranking the provider returned.
        return [by_id[i] for i in ids if i in by_id]

    async def cached_search(self, key: str, ttl_seconds: int) -> list[Job] | None:
        result = await self._run(self._cache_get_sync, key, ttl_seconds)
        return result  # type: ignore[no-any-return]

    def _cache_put_sync(self, key: str, ids: list[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO search_cache (cache_key, job_ids, created_at) "
                "VALUES (?, ?, ?)",
                (key, json.dumps(ids), _utcnow_iso()),
            )

    async def cache_search(self, key: str, jobs: list[Job]) -> None:
        await self._run(self._cache_put_sync, key, [job.id for job in jobs])

    # ------------------------------------------------------------- admin

    def _prune_sync(self, max_age_days: int) -> dict[str, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        with self._connect() as conn:
            # Cache entries first: they hold the job ids that keep postings
            # alive, and an expired entry is unreadable anyway.
            cache = conn.execute(
                "DELETE FROM search_cache WHERE created_at < ?", (cutoff,)
            ).rowcount
            # A posting goes only if nothing points at it. Saved jobs are the
            # user's shortlist and letters quote the posting they were written
            # for; deleting either's job would turn a shortlist entry or a
            # stored letter into a dangling reference. Live cache entries count
            # too — a cached search whose postings were pruned would answer
            # with fewer results than it promised.
            #
            # The cache ids are unpacked in Python rather than with json_each,
            # which is a JSON1 extension this package cannot assume is compiled
            # into every user's sqlite3.
            live_ids: set[str] = set()
            for row in conn.execute("SELECT job_ids FROM search_cache").fetchall():
                live_ids.update(json.loads(row["job_ids"]))
            # ``NOT IN (NULL)`` is never true in SQL — it evaluates to NULL and
            # the row is kept — so an empty set has to drop the clause rather
            # than emit a placeholder for nothing.
            ids = sorted(live_ids)
            clause = f" AND id NOT IN ({','.join('?' * len(ids))})" if ids else ""
            jobs = conn.execute(
                # The only interpolation is a run of '?' placeholders.
                "DELETE FROM jobs WHERE fetched_at < ? "  # noqa: S608
                "AND id NOT IN (SELECT job_id FROM saved_jobs) "
                "AND id NOT IN (SELECT job_id FROM letters)" + clause,
                (cutoff, *ids),
            ).rowcount
            # Letters whose resume was deleted before the cascade above existed.
            orphans = conn.execute(
                "DELETE FROM letters WHERE resume_id IS NOT NULL "
                "AND resume_id NOT IN (SELECT id FROM resumes)"
            ).rowcount
        result = {"jobs": jobs, "search_cache": cache, "orphaned_letters": orphans}
        if any(result.values()):
            log.info("storage.pruned", **result)
        return result

    async def prune(self, max_age_days: int = 30) -> dict[str, int]:
        """Drop stale postings and expired cache rows, and sweep up orphans.

        Nothing was ever deleted from this store. Every search wrote up to
        fifty postings, and a user running the server daily accumulated them
        forever — a file that only grows, holding job descriptions they saw
        once months ago. Resumes and letters are the user's own work and are
        never pruned; only fetched board data and its cache are.
        """
        return dict(await self._run(self._prune_sync, max_age_days))

    def _stats_sync(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
                for table in ("jobs", "resumes", "letters", "saved_jobs")
            }

    async def stats(self) -> dict[str, int]:
        return dict(await self._run(self._stats_sync))
