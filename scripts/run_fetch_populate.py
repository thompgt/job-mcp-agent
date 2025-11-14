"""Run fetch_data then populate_database via the in-process FastMCP client.

This script is safe to run from anywhere on Windows: it inserts the project root
into sys.path so `import server` works.
"""
import sys
from pathlib import Path
import dotenv
dotenv.load_dotenv()

# ensure project root (parent of scripts/) is on sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
from fastmcp import Client
from server.fastmcp_server import mcp


async def main():
    async with Client(mcp) as client:
        print("Calling fetch_data tool...")
        fetch_res = await client.call_tool("fetch_data", {"count": 5, "out_path": "jobs_test.json"})
        print("fetch_data ->", fetch_res)

        out_path = None
        # CallToolResult exposes .data / .structured_content depending on tool
        try:
            out_path = fetch_res.data.get("out_path")
        except Exception:
            try:
                out_path = fetch_res.structured_content.get("out_path")
            except Exception:
                out_path = None

        print("Calling populate_database tool... (out_path=", out_path, ")")
        pop_res = await client.call_tool("populate_database", {"out_path": out_path or "jobs_test.json"})
        print("populate_database ->", pop_res)


if __name__ == "__main__":
    asyncio.run(main())
