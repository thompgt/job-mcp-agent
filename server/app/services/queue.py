from typing import Dict, List, Optional
from threading import Lock


class InMemoryQueue:
    def __init__(self):
        self._jobs: Dict[int, dict] = {}
        self._next_id = 1
        self._claimed: Dict[int, bool] = {}
        self._lock = Lock()

    def add_jobs(self, jobs: List[dict]) -> int:
        with self._lock:
            count = 0
            for job in jobs:
                jid = self._next_id
                self._next_id += 1
                self._jobs[jid] = {"id": jid, "payload": job, "status": "queued"}
                self._claimed[jid] = False
                count += 1
            return count

    def list_jobs(self):
        with self._lock:
            return [
                {
                    "id": jid,
                    "title": j["payload"].get("jobTitle") or j["payload"].get("title"),
                    "company": j["payload"].get("companyName"),
                    "location": j["payload"].get("location"),
                }
                for jid, j in self._jobs.items()
            ]

    def claim(self, job_id: int) -> bool:
        with self._lock:
            if job_id not in self._jobs or self._claimed.get(job_id):
                return False
            self._claimed[job_id] = True
            self._jobs[job_id]["status"] = "claimed"
            return True

    def complete(self, job_id: int, result: dict) -> bool:
        with self._lock:
            if job_id not in self._jobs:
                return False
            self._jobs[job_id]["status"] = "completed"
            self._jobs[job_id]["result"] = result
            return True


_global_queue: Optional[InMemoryQueue] = None


def get_global_queue() -> InMemoryQueue:
    global _global_queue
    if _global_queue is None:
        _global_queue = InMemoryQueue()
    return _global_queue
