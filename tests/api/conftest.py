"""HTTP API fixtures.

The app is built with the shared temp-directory settings, and the lifespan is
bypassed in favour of injecting the already-started test service — otherwise
each client would build its own service against the real data directory.
"""

from __future__ import annotations

import httpx
import pytest

pytest.importorskip("fastapi", reason="needs the [api] extra")

from careercraft.api.app import create_app


@pytest.fixture
def app(settings, service):
    application = create_app(settings)
    application.state.service = service
    application.state.settings = settings
    return application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
