"""A small FastMCP server that exposes ingest/list/claim/complete as MCP tools.

This wraps the existing MCPController/queue implementation so you can run a
FastMCP server quickly without reimplementing business logic.
"""
from fastmcp import FastMCP
from server.app.controllers.mcp_controller import MCPController
from get_data import fetch_jobs
from pathlib import Path
from typing import Optional
import logging
import json
import hashlib

logger = logging.getLogger(__name__)


mcp = FastMCP("CareerCraft MCP")


@mcp.tool
def fetch_data(count: int = 100, out_path: str = "jobs.json") -> dict:
    """Fetch raw job data using the standalone `get_data.fetch_jobs` script.

    This is intentionally the first step/tool so clients can fetch and inspect
    the raw data before ingestion.
    Returns a small summary including number of items fetched and the output path.
    """
    logger.info("Tool fetch_data called: count=%s out_path=%s", count, out_path)
    jobs = fetch_jobs(count=count, out_path=out_path)
    p = Path(out_path).resolve()
    logger.info("Fetched %d jobs and wrote to %s", len(jobs), p)
    return {"fetched": len(jobs), "out_path": str(p)}

@mcp.tool
def populate_database(out_path: str = "jobs.json", mongo_url: str = "mongodb://localhost:27017") -> dict:
    """Populate a local MongoDB database called `jobs` from a fetch output JSON file.

    Behavior:
    - Reads `out_path` (default: jobs.json).
    - Parses the file to extract a list of job objects (supports common wrappers).
    - Connects to `mongo_url`, uses database `jobs` and collection `jobs`.
    - Deduplicates by computing a SHA256 of the job payload (stable JSON sorting) and
    inserts only jobs whose hash is not already present.
    Returns a summary dict: inserted, existing, errors, out_path.
    """
    logger.info("Tool populate_database called: out_path=%s mongo_url=%s", out_path, mongo_url)

    # Read file
    p = Path(out_path)
    if not p.exists():
        logger.warning("Jobs file does not exist: %s", out_path)
        return {"inserted": 0, "existing": 0, "errors": 0, "error": "file_not_found", "out_path": str(p)}

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.exception("Failed to read/parse JSON from %s: %s", out_path, e)
        return {"inserted": 0, "existing": 0, "errors": 0, "error": "json_read_failed", "out_path": str(p)}

    # Extract jobs list similar to controller._load_jobs_from_file
    jobs = []
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

    if not jobs:
        logger.warning("No jobs found in file: %s", out_path)
        return {"inserted": 0, "existing": 0, "errors": 0, "error": "no_jobs_found", "out_path": str(p)}

    # Import pymongo lazily so tool still exists if package missing
    try:
        import pymongo
    except Exception as e:
        logger.exception("pymongo is not available: %s", e)
        return {"inserted": 0, "existing": 0, "errors": 0, "error": "pymongo_not_installed", "out_path": str(p)}

    # Connect to Mongo
    try:
        client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        # quick ping
        client.admin.command("ping")
    except Exception as e:
        logger.exception("Failed to connect to MongoDB at %s: %s", mongo_url, e)
        return {"inserted": 0, "existing": 0, "errors": 0, "error": "mongo_connect_failed", "out_path": str(p)}

    db = client["jobs"]
    col = db["jobs"]
    # ensure unique index on source_hash
    try:
        col.create_index("source_hash", unique=True)
    except Exception:
        # ignore index creation errors
        pass

    inserted = 0
    existing = 0
    errors = 0

    for job in jobs:
        try:
            # canonical JSON for hashing
            payload_str = json.dumps(job, sort_keys=True, ensure_ascii=False)
            h = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            doc = {"source_hash": h, "payload": job}
            res = col.update_one({"source_hash": h}, {"$setOnInsert": doc}, upsert=True)
            # if an insert happened, upserted_id will be set
            if getattr(res, "upserted_id", None) is not None:
                inserted += 1
            else:
                existing += 1
        except Exception as e:
            logger.exception("Failed to insert job into Mongo: %s", e)
            errors += 1

    logger.info("populate_database completed: inserted=%s existing=%s errors=%s", inserted, existing, errors)
    return {"inserted": inserted, "existing": existing, "errors": errors, "out_path": str(p)}

@mcp.tool
def ingest(count: int = 100, out_path: Optional[str] = None) -> dict:
    """Ingest jobs into the MCP queue.

    If `out_path` is provided, the controller will ingest from that file and
    avoid refetching. Otherwise a fresh fetch will be performed.
    """
    logger.info("Tool ingest called: count=%s out_path=%s", count, out_path)
    controller = MCPController.instance()
    # for compatibility, support calling ingest with an out_path via environment
    # or pass None to trigger fresh fetch
    try:
        imported = controller.ingest(count=count, out_path=out_path)
        logger.info("Ingest completed: imported=%s", imported)
        return {"imported": int(imported)}
    except Exception as e:
        logger.exception("Ingest failed: %s", e)
        return {"imported": 0, "error": str(e)}


@mcp.tool
def list_jobs() -> list:
    logger.info("Tool list_jobs called")
    controller = MCPController.instance()
    return controller.list_jobs()


@mcp.tool
def claim(job_id: int) -> dict:
    logger.info("Tool claim called: %s", job_id)
    controller = MCPController.instance()
    ok = controller.claim_job(job_id)
    logger.info("Claim result for %s: %s", job_id, ok)
    return {"claimed": bool(ok)}


@mcp.tool
def complete(job_id: int, result: dict) -> dict:
    logger.info("Tool complete called: %s result_keys=%s", job_id, list(result.keys()) if isinstance(result, dict) else None)
    controller = MCPController.instance()
    ok = controller.complete_job(job_id, result)
    logger.info("Complete result for %s: %s", job_id, ok)
    return {"completed": bool(ok)}


if __name__ == "__main__":
    # Run as an HTTP transport (exposes /mcp)
    mcp.run(transport="http", host="127.0.0.1", port=8001, path="/mcp")
    