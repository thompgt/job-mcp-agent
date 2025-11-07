"""A small FastMCP server that exposes ingest/list/claim/complete as MCP tools.

This wraps the existing MCPController/queue implementation so you can run a
FastMCP server quickly without reimplementing business logic.
"""
from fastmcp import FastMCP
from server.app.controllers.mcp_controller import MCPController
from get_data import fetch_jobs


mcp = FastMCP("CareerCraft MCP")


@mcp.tool
def fetch_data(count: int = 100, out_path: str = "jobs.json") -> dict:
    """Fetch raw job data using the standalone `get_data.fetch_jobs` script.

    This is intentionally the first step/tool so clients can fetch and inspect
    the raw data before ingestion.
    Returns a small summary including number of items fetched and the output path.
    """
    jobs = fetch_jobs(count=count, out_path=out_path)
    return {"fetched": len(jobs), "out_path": str(out_path)}


@mcp.tool
def ingest(count: int = 100) -> dict:
    """Ingest jobs into the MCP queue. If you already fetched data with
    `fetch_data`, call ingest() to run the controller ingestion path (which will
    fetch again by default). For programmatic flows, call `fetch_data` first and
    then use lower-level queue APIs if you want to avoid refetching.

    Returns a simple dict summarizing the import.
    """
    controller = MCPController.instance()
    # call the controller.ingest() which calls get_data.fetch_jobs internally
    imported = controller.ingest()
    return {"imported": imported}


@mcp.tool
def list_jobs() -> list:
    controller = MCPController.instance()
    return controller.list_jobs()


@mcp.tool
def claim(job_id: int) -> dict:
    controller = MCPController.instance()
    ok = controller.claim_job(job_id)
    return {"claimed": bool(ok)}


@mcp.tool
def complete(job_id: int, result: dict) -> dict:
    controller = MCPController.instance()
    ok = controller.complete_job(job_id, result)
    return {"completed": bool(ok)}


if __name__ == "__main__":
    # Run as an HTTP transport (exposes /mcp)
    mcp.run(transport="http", host="127.0.0.1", port=8001, path="/mcp")
