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
