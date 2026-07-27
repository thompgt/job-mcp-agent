"""A provider that is never available.

Used when the operator has turned generation off, and in tests. Its whole
purpose is to make "no language model" an ordinary, well-typed state rather
than an import error or a None check scattered through the callers.
"""

from __future__ import annotations

from typing import AsyncIterator

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
        raise ProviderError(
            "No language model is configured.",
            remedy="Install Ollama from https://ollama.com and run `ollama serve`.",
        )
        yield ""  # pragma: no cover - unreachable, keeps this an async generator
