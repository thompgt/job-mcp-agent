"""The HTTP API.

Secondary to the MCP server, and deliberately thinner: it exists to back the
web UI for people who do not use an MCP host. Both surfaces call the same
:class:`CareerCraftService`, which is the whole point of the consolidation —
v1 implemented the pipeline once in the MCP server and again in the API, and
by the end the two had drifted into giving different answers.

Errors map centrally. A domain error becomes a status code plus a body with
``code``, ``message`` and ``remedy``, so a client can branch on the code and
still show a human the fix.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from careercraft import __version__
from careercraft.api.routes import router
from careercraft.errors import (
    AccessDenied,
    CareerCraftError,
    DependencyMissing,
    NotFound,
    ProviderError,
    ValidationFailed,
)
from careercraft.logging import configure_logging, get_logger
from careercraft.service import build_service
from careercraft.settings import Settings, get_settings

log = get_logger(__name__)

DESCRIPTION = """\
Resume parsing, job matching and cover letter drafting — all local.

This API backs the CareerCraft web UI. The primary interface to the same
functionality is the MCP server (`careercraft-mcp`), which plugs into Claude
Desktop, Claude Code and Cursor.

`GET /api/capabilities` reports which optional features this install has;
anything unavailable comes with the command that enables it.
"""

#: Domain error -> HTTP status. Anything not listed is a 500, which is correct:
#: an error we did not classify is one we did not anticipate.
_STATUS: dict[type[CareerCraftError], int] = {
    NotFound: 404,
    ValidationFailed: 400,
    AccessDenied: 403,
    DependencyMissing: 501,
    ProviderError: 502,
}


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        service = build_service(resolved)
        await service.startup()
        app.state.service = service
        app.state.settings = resolved
        log.info("api.ready", version=__version__)
        try:
            yield
        finally:
            await service.shutdown()

    app = FastAPI(
        title="CareerCraft",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    # Settings are on state before the lifespan runs too, so the exception
    # handlers and dependencies work even for requests that arrive during
    # startup or in tests that never enter the lifespan.
    app.state.settings = resolved

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=bool(resolved.auth_token),
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(CareerCraftError)
    async def _domain_error(request: Request, exc: CareerCraftError) -> JSONResponse:
        status = _STATUS.get(type(exc), 500)
        if status >= 500:
            log.warning("api.error", code=exc.code, path=request.url.path, message=exc.message)
        return JSONResponse(
            status_code=status,
            content={"code": exc.code, "message": exc.message, "remedy": exc.remedy},
        )

    app.include_router(router, prefix="/api")
    return app


app = create_app()
