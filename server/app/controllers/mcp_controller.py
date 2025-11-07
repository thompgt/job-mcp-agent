from typing import List
from ..services.queue import get_global_queue

from get_data import fetch_jobs


class MCPController:
    _instance = None

    def __init__(self):
        self.queue = get_global_queue()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = MCPController()
        return cls._instance

    def ingest(self) -> int:
        jobs = fetch_jobs()
        return self.queue.add_jobs(jobs)

    def list_jobs(self) -> List[dict]:
        return self.queue.list_jobs()

    def claim_job(self, job_id: int) -> bool:
        return self.queue.claim(job_id)

    def complete_job(self, job_id: int, result: dict) -> bool:
        return self.queue.complete(job_id, result)
