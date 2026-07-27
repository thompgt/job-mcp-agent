"""A provider that is never available.

Used when the operator has turned generation off, and in tests. Its whole
purpose is to make "no language model" an ordinary, well-typed state rather
than an import error or a None check scattered through the callers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from careercraft.errors import ProviderError
from careercraft.llm import ChatMessage


class NullProvider:
    name = "null"

    async def is_available(self) -> bool:
        return False

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        raise ProviderError(
            "No language model is configured.",
            remedy="Install Ollama from https://ollama.com and run `ollama serve`.",
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        # The unreachable yield is what makes this an async generator rather
        # than a coroutine, so it satisfies the LLMProvider protocol. Without
        # it, calling stream() would raise before returning an iterator, and
        # `async for` over the result would fail with a different error.
        raise ProviderError(
            "No language model is configured.",
            remedy="Install Ollama from https://ollama.com and run `ollama serve`.",
        )
        yield ""  # type: ignore[unreachable]
