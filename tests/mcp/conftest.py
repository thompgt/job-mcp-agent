"""In-memory MCP client fixtures.

``Client(server)`` speaks the real protocol over an in-process transport: the
same tool dispatch, the same schema validation, the same error mapping as a
stdio subprocess, without spawning one. Every assertion here is therefore
about the wire contract, not about Python function calls.
"""

from __future__ import annotations

import pytest
from fastmcp import Client, FastMCP

from careercraft.mcp.server import build_server


@pytest.fixture
def server(settings, service) -> FastMCP:
    return build_server(settings, service=service)


@pytest.fixture
async def client(server: FastMCP):
    async with Client(server) as c:
        yield c
