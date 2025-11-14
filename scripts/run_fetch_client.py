import sys
from pathlib import Path

# ensure project root (two levels up from scripts/) is on sys.path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
import json
from fastmcp import Client
from server.fastmcp_server import mcp


async def main():
    async with Client(mcp) as client:
        print("Calling fetch_data tool...")
        res = await client.call_tool("fetch_data", {"count": 5, "out_path": "jobs_test.json"})
        print("tool result:", res)


if __name__ == "__main__":
    asyncio.run(main())
