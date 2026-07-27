"""The language-model contract.

Deliberately a Protocol in the shared layer rather than an adapter import, so
``core`` can depend on the *shape* of a chat model without depending on any
implementation. Implementations live in :mod:`careercraft.adapters.llm`.

Only Ollama ships. That is a product decision, not a technical limit: this
server reads your resume, and sending it to a third-party API by default is
not a choice a tool should make for you. The seam is here so that adding a
provider is a new file rather than a refactor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, TypedDict, runtime_checkable


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    """A chat-completion backend."""

    name: str

    async def is_available(self) -> bool:
        """Whether the backend can actually serve a request right now.

        Must not raise, and must be cheap — callers use it to decide between
        generating prose and returning a structured brief, on every request.
        """
        ...

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str: ...

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...
