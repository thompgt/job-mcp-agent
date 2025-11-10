from typing import List, Optional
import json
import logging
from pathlib import Path

from ..services.queue import get_global_queue

from get_data import fetch_jobs


logger = logging.getLogger(__name__)


class MCPController:
    _instance = None

    def __init__(self, redis_url: Optional[str] = None, mongo_url: Optional[str] = None):
        # get_global_queue can choose Mongo/Redis/in-memory based on availability
        try:
            if mongo_url:
                self.queue = get_global_queue(redis_url=redis_url)
            else:
                self.queue = get_global_queue()
        except Exception as e:
            logger.exception("Failed to initialize queue: %s", e)
            # fallback to in-memory queue
            self.queue = get_global_queue()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = MCPController()
        return cls._instance

    def ingest(self, jobs: Optional[List[dict]] = None, count: int = 100, out_path: Optional[str] = None) -> int:
        """Ingest jobs into the queue.

        - If `jobs` is provided, use it directly.
        - Else if `out_path` is provided, load JSON from file.
        - Otherwise call fetch_jobs(count) to fetch fresh data.

        Returns number of jobs added.
        """
        try:
            if jobs is None:
                if out_path:
                    jobs = self._load_jobs_from_file(out_path)
                    logger.info("Loaded %d jobs from file %s", len(jobs), out_path)
                else:
                    logger.info("Fetching %d jobs via fetch_jobs()", count)
                    jobs = fetch_jobs(count=count, out_path=out_path or "jobs.json")
                    logger.info("Fetched %d jobs", len(jobs))

            if not jobs:
                logger.warning("No jobs to ingest")
                return 0

            added = self.queue.add_jobs(jobs)
            logger.info("Ingested %d jobs into queue", added)
            return int(added)
        except Exception as e:
            logger.exception("Error during ingest: %s", e)
            return 0

    def ingest_from_file(self, path: str) -> int:
        """Convenience method to ingest jobs from a JSON file path."""
        jobs = self._load_jobs_from_file(path)
        return self.ingest(jobs=jobs)

    def _load_jobs_from_file(self, path: str) -> List[dict]:
        p = Path(path)
        if not p.exists():
            logger.warning("Jobs file does not exist: %s", path)
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.exception("Failed to read jobs json from %s: %s", path, e)
            return []

        jobs: List[dict] = []
        if isinstance(data, dict):
            for k in ("jobs", "data", "results", "items"):
                if k in data and isinstance(data[k], list):
                    jobs = data[k]
                    break
            if not jobs:
                lists = [(k, v) for k, v in data.items() if isinstance(v, list)]
                if lists:
                    jobs = max(lists, key=lambda kv: len(kv[1]))[1]
        elif isinstance(data, list):
            jobs = data
        return jobs

    def list_jobs(self) -> List[dict]:
        try:
            return self.queue.list_jobs()
        except Exception as e:
            logger.exception("Failed to list jobs: %s", e)
            return []

    def claim_job(self, job_id: int) -> bool:
        try:
            return self.queue.claim(job_id)
        except Exception as e:
            logger.exception("Failed to claim job %s: %s", job_id, e)
            return False

    def complete_job(self, job_id: int, result: dict) -> bool:
        try:
            return self.queue.complete(job_id, result)
        except Exception as e:
            logger.exception("Failed to complete job %s: %s", job_id, e)
            return False
