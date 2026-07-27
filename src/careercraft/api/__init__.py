"""The HTTP API that backs the web UI. Needs the ``[api]`` extra."""

from careercraft.api.app import create_app

__all__ = ["create_app"]
