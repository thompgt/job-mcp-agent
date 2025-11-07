"""Convenience runner for the FastMCP server.

This runner will call the `fetch_data` FastMCP tool before starting the
server so the job data is fetched and saved locally (via `get_data.py`).
"""
import os
from server.fastmcp_server import mcp, fetch_data


def main() -> None:
    # Optionally control fetch behavior via env vars
    do_fetch = os.getenv("MCP_FETCH_ON_START", "1").lower() in ("1", "true", "yes")
    if do_fetch:
        try:
            count = int(os.getenv("MCP_FETCH_COUNT", "100"))
            out_path = os.getenv("MCP_FETCH_OUT", "jobs.json")
            print(f"Running fetch_data(count={count}, out_path={out_path}) before server start...")
            result = fetch_data(count=count, out_path=out_path)
            print("Fetch result:", result)
        except Exception as e:
            print("Initial fetch failed:", e)

    # default: HTTP transport on /mcp at port 8001
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8001"))
    path = os.getenv("MCP_PATH", "/mcp")
    print(f"Starting FastMCP server on http://{host}:{port}{path}")
    mcp.run(transport="http", host=host, port=port, path=path)


if __name__ == "__main__":
    main()
