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
