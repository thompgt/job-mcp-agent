from fastapi import FastAPI
import logging
import os

from .api.routes import router as api_router


# Configure logging for app
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def create_app() -> FastAPI:
    app = FastAPI(title="Job MCP Server (dev)")
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
