from typing import Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)

try:
    import redis
except Exception:
    redis = None
try:
    import pymongo
    from pymongo import ReturnDocument
except Exception:
    pymongo = None
    ReturnDocument = None


class InMemoryQueue:
    """Fallback in-memory queue for local dev/testing."""

    def __init__(self):
        self._jobs: Dict[int, dict] = {}
        self._next_id = 1

    def add_jobs(self, jobs: List[dict]) -> int:
        count = 0
        for job in jobs:
            jid = self._next_id
            self._next_id += 1
            self._jobs[jid] = {"id": jid, "payload": job, "status": "queued"}
            count += 1
        return count

    def list_jobs(self):
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
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.get("status") == "claimed":
            return False
        job["status"] = "claimed"
        return True

    def complete(self, job_id: int, result: dict) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job["status"] = "completed"
        job["result"] = result
        return True


class RedisQueue:
    """Redis-backed queue implementation.

    Uses keys:
    - jobs:next_id (INCR) -> next job id
    - job:{id} (HASH) -> fields: payload (json), status, result
    - jobs:queue (LIST) -> queued job ids
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        if redis is None:
            raise RuntimeError("redis package is not available")
        self._r = redis.Redis.from_url(redis_url, decode_responses=True)

        # Test connection
        try:
            self._r.ping()
        except Exception as e:
            raise

    def add_jobs(self, jobs: List[dict]) -> int:
        pipe = self._r.pipeline()
        count = 0
        for job in jobs:
            jid = self._r.incr("jobs:next_id")
            key = f"job:{jid}"
            pipe.hset(key, mapping={
                "payload": json.dumps(job),
                "status": "queued",
            })
            pipe.rpush("jobs:queue", jid)
            count += 1
        pipe.execute()
        return count

    def list_jobs(self):
        # scan for job:* keys and return a simple summary
        out = []
        for key in self._r.scan_iter(match="job:*"):
            try:
                jid = int(key.split(":", 1)[1])
            except Exception:
                continue
            data = self._r.hget(key, "payload")
            if not data:
                continue
            payload = json.loads(data)
            out.append({
                "id": jid,
                "title": payload.get("jobTitle") or payload.get("title"),
                "company": payload.get("companyName"),
                "location": payload.get("location"),
            })
        return out

    def claim(self, job_id: int) -> bool:
        key = f"job:{job_id}"
        # use WATCH/MULTI to ensure atomic check-and-set
        with self._r.pipeline() as pipe:
            try:
                while True:
                    try:
                        pipe.watch(key)
                        status = pipe.hget(key, "status")
                        if status is None:
                            pipe.unwatch()
                            return False
                        if status == "claimed":
                            pipe.unwatch()
                            return False
                        pipe.multi()
                        pipe.hset(key, "status", "claimed")
                        pipe.execute()
                        return True
                    except redis.WatchError:
                        continue
            finally:
                try:
                    pipe.reset()
                except Exception:
                    pass

    def complete(self, job_id: int, result: dict) -> bool:
        key = f"job:{job_id}"
        if not self._r.exists(key):
            return False
        self._r.hset(key, mapping={"status": "completed", "result": json.dumps(result)})
        return True


class MongoQueue:
    """MongoDB-backed queue implementation.

    Collections used:
    - counters: document {_id: 'jobid', seq: int}
    - jobs: documents {id: int, payload: dict, status: str, result: dict}
    - jobs_queue: documents {job_id: int, enqueued_at: datetime}
    """

    def __init__(self, mongo_url: str = "mongodb://localhost:27017", dbname: str = "job_mcp"):
        if pymongo is None:
            raise RuntimeError("pymongo package is not available")
        self._client = pymongo.MongoClient(mongo_url)
        self._db = self._client[dbname]
        self._jobs = self._db.jobs
        self._queue = self._db.jobs_queue

        # create indexes for performance
        try:
            self._jobs.create_index("id", unique=True)
            self._queue.create_index("job_id")
        except Exception:
            pass

    def _next_id(self) -> int:
        c = self._db.counters.find_one_and_update(
            {"_id": "jobid"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER
        )
        return int(c["seq"])

    def add_jobs(self, jobs: List[dict]) -> int:
        docs = []
        count = 0
        for job in jobs:
            jid = self._next_id()
            doc = {"id": jid, "payload": job, "status": "queued"}
            docs.append(doc)
            self._queue.insert_one({"job_id": jid})
            count += 1
        if docs:
            self._jobs.insert_many(docs)
        return count

    def list_jobs(self):
        out = []
        for doc in self._jobs.find({}):
            payload = doc.get("payload", {}) or {}
            out.append({
                "id": int(doc.get("id")),
                "title": payload.get("jobTitle") or payload.get("title"),
                "company": payload.get("companyName"),
                "location": payload.get("location"),
            })
        return out

    def claim(self, job_id: int) -> bool:
        res = self._jobs.find_one_and_update(
            {"id": job_id, "status": "queued"}, {"$set": {"status": "claimed"}}, return_document=ReturnDocument.AFTER
        )
        return res is not None

    def complete(self, job_id: int, result: dict) -> bool:
        res = self._jobs.find_one_and_update({"id": job_id}, {"$set": {"status": "completed", "result": result}})
        return res is not None


_global_queue = None


def get_global_queue(redis_url: str = "redis://localhost:6379/0"):
    global _global_queue
    if _global_queue is not None:
        return _global_queue

    # Try to create Redis-backed queue first
    if redis is not None:
        try:
            q = RedisQueue(redis_url=redis_url)
            _global_queue = q
            logger.info("Using Redis-backed queue at %s", redis_url)
            return _global_queue
        except Exception as e:
            logger.warning("Redis not available (%s). Falling back to in-memory queue.", e)

    # Fallback
    _global_queue = InMemoryQueue()
    logger.info("Using in-memory queue (fallback)")
    return _global_queue
