"""A small FastMCP server that exposes ingest/list/claim/complete as MCP tools.

This wraps the existing MCPController/queue implementation so you can run a
FastMCP server quickly without reimplementing business logic.
"""
from fastmcp import FastMCP
from server.app.controllers.mcp_controller import MCPController
from get_data import fetch_jobs
from server.app.services.resume_parser import parse_resume_file
from pathlib import Path
from typing import Optional
import logging
import os
from urllib.parse import quote_plus

# optional: load .env in development if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
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
def parse_resume(resume_path: str) -> dict:
    """Parse a resume file (pdf/docx/txt) and return structured metadata.

    resume_path: filesystem path to a resume file. The tool will call
    `server.app.services.resume_parser.parse_resume_file` and return the parsed
    dictionary. Returns an error key on failure.
    """
    logger.info("Tool parse_resume called: %s", resume_path)
    p = Path(resume_path)
    if not p.exists():
        logger.warning("Resume file does not exist: %s", resume_path)
        return {"error": "file_not_found", "path": str(p)}
    try:
        parsed = parse_resume_file(p)
        logger.info("Parsed resume %s: name=%s skills=%d", resume_path, parsed.get("name"), len(parsed.get("skills", [])))
        return {"parsed": parsed, "path": str(p)}
    except Exception as e:
        logger.exception("Failed to parse resume %s: %s", resume_path, e)
        return {"error": "parse_failed", "detail": str(e), "path": str(p)}

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

    # Allow overriding connection via environment variables (.env)
    env_mongo = os.getenv("MONGO_URL")
    if env_mongo:
        # If the env url contains a placeholder like <db_password>, replace it from MONGO_PASS
        if "<db_password>" in env_mongo:
            env_mongo = env_mongo.replace("<db_password>", quote_plus(os.getenv("MONGO_PASS", "")))
        mongo_url = env_mongo
    else:
        # support constructing from parts
        m_user = os.getenv("MONGO_USER")
        print(f"m_user: {m_user}")
        m_pass = os.getenv("MONGO_PASS")
        print(f"m_pass: {m_pass}")
        if m_user and m_pass:
            mongo_url = f"mongodb+srv://{m_user}:{m_pass}@cluster0.xdbs2l7.mongodb.net/"
            print(mongo_url)
        else:
            print("Using default mongo_url:", mongo_url)
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

    # Import pymongo lazily so tool still exists if package missing; allow mongomock fallback
    pymongo = None
    mongomock = None
    use_mongomock = False
    try:
        import pymongo
        from pymongo.errors import DuplicateKeyError
    except Exception:
        pymongo = None

    try:
        import mongomock
    except Exception:
        mongomock = None

    client = None
    if pymongo is not None:
        try:
            client = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
            # quick ping to verify connection
            client.admin.command("ping")
            logger.info("Connected to MongoDB at %s", mongo_url)
        except Exception as e:
            logger.warning("Failed to connect to MongoDB at %s: %s", mongo_url, e)
            client = None

    if client is None:
        if mongomock is not None:
            logger.info("Falling back to mongomock (in-memory MongoDB) for populate_database")
            client = mongomock.MongoClient()
            use_mongomock = True
        else:
            logger.exception("pymongo not available or MongoDB unreachable and mongomock not installed")
            return {"inserted": 0, "existing": 0, "errors": 0, "error": "mongo_connect_failed", "out_path": str(p)}

    db = client["jobs"]
    col = db["jobs"]
    # ensure unique index on source_hash (idempotent)
    try:
        col.create_index("source_hash", unique=True)
    except Exception:
        logger.debug("create_index on source_hash failed or already exists; continuing")

    # normalize and insert with DuplicateKey handling to avoid races
    # DuplicateKeyError is available from pymongo if present; if using mongomock it'll raise a generic exception
    try:
        from pymongo.errors import DuplicateKeyError
    except Exception:
        class DuplicateKeyError(Exception):
            pass

    def _normalize(job_obj: dict) -> dict:
        # shallow copy then drop common ephemeral fields that would make duplicates differ
        j = dict(job_obj)
        for fld in ("fetched_at", "scraped_at", "request_id", "crawl_id", "id"):
            # note: we deliberately don't drop job id if you want it preserved in payload,
            # but many feeds include changing IDs; remove only when necessary
            j.pop(fld, None)
        return j

    inserted = 0
    existing = 0
    errors = 0

    for job in jobs:
        try:
            norm = _normalize(job)
            payload_str = json.dumps(norm, sort_keys=True, ensure_ascii=False)
            h = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            doc = {"source_hash": h, "payload": job}
            try:
                res = col.update_one({"source_hash": h}, {"$setOnInsert": doc}, upsert=True)
                if getattr(res, "upserted_id", None) is not None:
                    inserted += 1
                else:
                    existing += 1
            except DuplicateKeyError:
                # concurrent insert by another process; treat as existing
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


@mcp.tool
def generate_cover_letter_tool(resume: dict, job: dict, model_name: str = "llama3.2", temperature: float = 0.7) -> dict:
    """Generate a cover letter string from a parsed resume dict and a job dict.

    Returns {'cover_letter': str} or {'error': '...'} on failure.
    """
    try:
        # lazy import to avoid heavy deps at module import time
        from server.app.services.cover_letter_generator import generate_cover_letter

        letter = generate_cover_letter(resume, job, model_name=model_name, temperature=temperature)
        return {"cover_letter": letter}
    except Exception as e:
        logger.exception("generate_cover_letter_tool failed: %s", e)
        return {"error": "generate_failed", "detail": str(e)}


if __name__ == "__main__":
    # Run as an HTTP transport (exposes /mcp)
    mcp.run(transport="http", host="127.0.0.1", port=8001, path="/mcp")
    