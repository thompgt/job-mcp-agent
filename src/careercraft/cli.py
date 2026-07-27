"""Command line entry point.

``careercraft-mcp`` with no arguments starts the MCP server on stdio, which is
what an MCP host's config block invokes. The subcommands exist so the same
install is useful from a terminal without a host: ``doctor`` in particular is
the first thing to run when a host reports the server as failed, because it
prints to *stdout* deliberately — it is not speaking JSON-RPC.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from careercraft import __version__
from careercraft.errors import CareerCraftError, DependencyMissing
from careercraft.logging import configure_logging, get_logger
from careercraft.settings import Settings, get_settings

log = get_logger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="careercraft-mcp",
        description="CareerCraft — resume parsing, job matching and cover letters over MCP.",
    )
    parser.add_argument("--version", action="version", version=f"careercraft-mcp {__version__}")
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Overrides CAREERCRAFT_LOG_LEVEL.",
    )

    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the MCP server (default).")
    serve.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=None,
        help="stdio for a local host such as Claude Desktop; http to expose it over a port.",
    )
    serve.add_argument("--host", default=None, help="HTTP bind address. Default 127.0.0.1.")
    serve.add_argument("--port", type=int, default=None, help="HTTP port. Default 8000.")
    serve.add_argument("--path", default=None, help="HTTP mount path. Default /mcp.")

    api = sub.add_parser("api", help="Run the HTTP API that backs the web UI.")
    api.add_argument("--host", default=None, help="Bind address. Default 127.0.0.1.")
    api.add_argument("--port", type=int, default=None, help="Port. Default 8000.")
    api.add_argument("--reload", action="store_true", help="Reload on source changes.")

    sub.add_parser("doctor", help="Report what this install can do, and what is missing.")
    sub.add_parser("info", help="Print resolved settings as JSON.")

    parse = sub.add_parser("parse", help="Parse a resume and print the result as JSON.")
    parse.add_argument("path", help="Path to a .pdf, .docx, .txt or .md resume.")
    parse.add_argument("--no-store", action="store_true", help="Do not persist the result.")

    return parser


def _apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    for field, value in (
        ("transport", getattr(args, "transport", None)),
        ("host", getattr(args, "host", None)),
        ("port", getattr(args, "port", None)),
        ("http_path", getattr(args, "path", None)),
        ("log_level", args.log_level),
    ):
        if value is not None:
            setattr(settings, field, value)
    return settings


def _cmd_serve(settings: Settings) -> int:
    from careercraft.mcp.server import build_server

    settings.ensure_dirs()
    server = build_server(settings)

    if settings.transport == "http":
        # Refuses a non-loopback bind without an auth token, and refuses a
        # wildcard CORS origin alongside one. An MCP server speaks to a model
        # that will do what a web page tells it to; this is not a formality.
        settings.check_bind_safety()
        log.info(
            "server.http",
            url=f"http://{settings.host}:{settings.port}{settings.http_path}",
        )
        server.run(
            transport="http",
            host=settings.host,
            port=settings.port,
            path=settings.http_path,
            show_banner=False,
        )
    else:
        # show_banner=False is load-bearing: the banner would go to stdout and
        # corrupt the very first JSON-RPC frame.
        server.run(transport="stdio", show_banner=False)
    return 0


def _cmd_api(settings: Settings) -> int:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise DependencyMissing("The HTTP API", "api") from exc

    # The API is transport-independent, but check_bind_safety keys off it, and
    # exposing this on a routable interface has exactly the same consequences
    # as exposing the MCP server there.
    settings.transport = "http"
    settings.check_bind_safety()
    settings.ensure_dirs()

    log.info("api.starting", url=f"http://{settings.host}:{settings.port}/docs")
    uvicorn.run(
        "careercraft.api.app:app",
        host=settings.host,
        port=settings.port,
        log_config=None,  # our structlog handlers already own stderr
        access_log=False,
    )
    return 0


def _cmd_doctor(settings: Settings) -> int:
    import anyio

    from careercraft.capabilities import collect
    from careercraft.service import build_service

    async def probe() -> bool:
        service = build_service(settings)
        return await service.llm_available()

    reachable = anyio.run(probe)
    report = collect(transport=settings.transport, ollama_reachable=reachable)

    print(f"careercraft-mcp {report.version}  (python {report.python})")
    print(f"data dir: {settings.data_dir}")
    print()
    missing = []
    for cap in report.capabilities:
        mark = "ok  " if cap.available else "MISS"
        print(f"  [{mark}] {cap.name:<20} {cap.detail}")
        if not cap.available and cap.enable_with:
            missing.append((cap.name, cap.enable_with))
    print()
    print(f"default match strategy: {report.default_match_strategy}")
    if missing:
        print("\nTo enable the rest:")
        for name, command in missing:
            print(f"  {name:<20} {command}")
    else:
        print("\nEverything is available.")
    return 0


def _cmd_info(settings: Settings) -> int:
    payload = settings.model_dump(mode="json")
    payload.pop("auth_token", None)  # never print a secret, even a local one
    print(json.dumps(payload, indent=2, default=str))
    return 0


def _cmd_parse(settings: Settings, path: str, *, persist: bool) -> int:
    import anyio

    from careercraft.adapters.files import resolve_allowed
    from careercraft.service import build_service

    async def run() -> int:
        service = build_service(settings)
        await service.startup()
        target = resolve_allowed(path, settings.allowed_paths, transport="stdio")
        resume = await service.parse_resume(path=target, persist=persist)
        print(json.dumps(resume.model_dump(mode="json"), indent=2))
        return 0

    return anyio.run(run)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = _apply_overrides(get_settings(), args)
    configure_logging(settings.log_level)

    command = args.command or "serve"
    try:
        if command == "serve":
            return _cmd_serve(settings)
        if command == "api":
            return _cmd_api(settings)
        if command == "doctor":
            return _cmd_doctor(settings)
        if command == "info":
            return _cmd_info(settings)
        if command == "parse":
            return _cmd_parse(settings, args.path, persist=not args.no_store)
    except CareerCraftError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
