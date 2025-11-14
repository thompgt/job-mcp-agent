import sys
from pathlib import Path

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
        fetch_res = await client.call_tool("fetch_data", {"count": 10, "out_path": "jobs_test.json"})
        print("fetch_data result:", fetch_res)

        print("Calling populate_database tool...")
        pop_res = await client.call_tool("populate_database", {"out_path": fetch_res["out_path"]})
        print("populate_database result:", pop_res)

if __name__ == "__main__":
    asyncio.run(main())