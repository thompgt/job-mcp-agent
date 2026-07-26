"""Pure domain logic.

Nothing in here may import a transport, a web framework or a storage driver —
see the ruff ``flake8-tidy-imports`` ban list in pyproject.toml. The point is
that the whole pipeline stays unit-testable, and importable, with none of the
optional extras installed.
"""
