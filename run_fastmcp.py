"""Convenience runner for the FastMCP server.

This runner will call the `fetch_data` FastMCP tool before starting the
server so the job data is fetched and saved locally (via `get_data.py`).
"""
import os
import logging
from server.fastmcp_server import mcp, fetch_data


# configure logging for the runner
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("run_fastmcp")


def main() -> None:
    # Optionally control fetch behavior via env vars
    do_fetch = os.getenv("MCP_FETCH_ON_START", "1").lower() in ("1", "true", "yes")
    if do_fetch:
        try:
            count = int(os.getenv("MCP_FETCH_COUNT", "100"))
            out_path = os.getenv("MCP_FETCH_OUT", "jobs.json")
            logger.info("Running fetch_data(count=%s, out_path=%s) before server start...", count, out_path)
            result = fetch_data(count=count, out_path=out_path)
            logger.info("Fetch result: %s", result)
        except Exception as e:
            logger.exception("Initial fetch failed: %s", e)

    # default: HTTP transport on /mcp at port 8001
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8001"))
    path = os.getenv("MCP_PATH", "/mcp")
    logger.info("Starting FastMCP server on http://%s:%s%s", host, port, path)
    mcp.run(transport="http", host=host, port=port, path=path)


if __name__ == "__main__":
    main()
