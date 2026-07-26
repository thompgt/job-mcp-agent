"""Domain errors.

Every error carries a ``remedy``: a sentence the user can act on, naming the
exact command where one exists. The MCP layer surfaces it verbatim, because
the model reading the tool result is usually the one who has to fix the
problem.
"""

from __future__ import annotations


class CareerCraftError(Exception):
    """Base class for every error this package raises deliberately."""

    #: Filled in by the MCP/API layers when mapping to a protocol error.
    code = "careercraft_error"

    def __init__(self, message: str, *, remedy: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy

    def __str__(self) -> str:
        if self.remedy:
            return f"{self.message} {self.remedy}"
        return self.message


class DependencyMissing(CareerCraftError):
    """An optional extra is needed for the requested capability."""

    code = "dependency_missing"

    def __init__(self, feature: str, extra: str, *, package: str | None = None) -> None:
        pkg = package or f"careercraft-mcp[{extra}]"
        super().__init__(
            f"{feature} needs the optional '{extra}' extra, which is not installed.",
            remedy=(
                f"Install it with `uv pip install '{pkg}'` "
                f"(or `pip install '{pkg}'`), then restart the server."
            ),
        )
        self.feature = feature
        self.extra = extra


class NotFound(CareerCraftError):
    """A referenced record does not exist."""

    code = "not_found"

    def __init__(self, kind: str, identifier: str, *, remedy: str | None = None) -> None:
        super().__init__(f"No {kind} found with id {identifier!r}.", remedy=remedy)
        self.kind = kind
        self.identifier = identifier


class ValidationFailed(CareerCraftError):
    """The caller supplied arguments that cannot be honoured."""

    code = "validation_failed"


class AccessDenied(CareerCraftError):
    """A filesystem path or operation is outside what this server may touch."""

    code = "access_denied"


class ProviderError(CareerCraftError):
    """An upstream service (job board, Ollama) failed or is unreachable."""

    code = "provider_error"
