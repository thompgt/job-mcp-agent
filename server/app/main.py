from fastapi import FastAPI

from .api.routes import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Job MCP Server (dev)")
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
