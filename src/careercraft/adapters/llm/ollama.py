"""Ollama backend, over its HTTP API directly.

v1 reached Ollama through ``langchain_community.ChatOllama``, which meant a
~120 MB dependency tree — LangChain core, community, several serialisation
layers — for a single ``invoke()`` call against one JSON endpoint. This is
that endpoint.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from careercraft.errors import ProviderError
from careercraft.llm import ChatMessage
from careercraft.logging import get_logger
from careercraft.retry import DEFAULT_ATTEMPTS, with_retry

log = get_logger(__name__)

#: Availability is checked before every letter, so the probe has to be quick;
#: a dead daemon should fail in a moment, not hold the tool call open.
_PROBE_TIMEOUT = 2.0


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "llama3.2:1b",
        timeout: float = 180.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = client
        self._owned: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """One client for the provider's lifetime, reused across calls.

        The per-call timeout differs enormously — two seconds for the
        availability probe, three minutes for generation — so it is passed per
        request rather than baked into the client.
        """
        if self._client is not None:
            return self._client
        if self._owned is None or self._owned.is_closed:
            self._owned = httpx.AsyncClient(timeout=self.timeout)
        return self._owned

    async def aclose(self) -> None:
        if self._owned is not None and not self._owned.is_closed:
            await self._owned.aclose()
        self._owned = None

    async def _request(
        self, method: str, path: str, timeout: float, *, retries: int = 1, **kwargs: Any
    ) -> Any:
        async def send() -> httpx.Response:
            response = await self._get_client().request(
                method, f"{self.base_url}{path}", timeout=timeout, **kwargs
            )
            response.raise_for_status()
            return response

        # ``retries=1`` means one attempt: the probes below are meant to answer
        # "is the daemon up right now" quickly, and backing off would turn a
        # two-second capability check into a slow one.
        return await with_retry(send, what=f"ollama {method} {path}", attempts=retries)

    async def is_available(self) -> bool:
        """True when a letter can actually be generated. Never raises.

        A reachable daemon is not enough. A fresh Ollama install answers
        ``/api/tags`` perfectly well with an empty model list, so probing only
        for reachability made ``careercraft doctor`` report letter writing as
        available and then fail on the first request with a 404 — which is the
        opposite of what the capability report is for.
        """
        return self.model in set(await self.list_models())

    async def daemon_reachable(self) -> bool:
        """Whether the daemon answers at all, regardless of models."""
        try:
            await self._request("GET", "/api/tags", _PROBE_TIMEOUT)
        except Exception:
            return False
        return True

    async def list_models(self) -> list[str]:
        try:
            response = await self._request("GET", "/api/tags", _PROBE_TIMEOUT)
        except Exception:
            return []
        payload = response.json()
        return [m.get("name", "") for m in payload.get("models", []) if m.get("name")]

    def _unreachable(self, exc: Exception) -> ProviderError:
        return ProviderError(
            f"Could not reach Ollama at {self.base_url}: {exc}",
            remedy=(
                "Start it with `ollama serve`, pull the model with "
                f"`ollama pull {self.model}`, or set CAREERCRAFT_OLLAMA_BASE_URL "
                "if the daemon runs elsewhere."
            ),
        )

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            body["options"]["num_predict"] = max_tokens

        log.info("ollama.complete", model=body["model"], messages=len(messages))
        try:
            # Generation is the expensive call and the one a user waits on,
            # so a dropped connection or a 503 is worth another go. A 404
            # (no such model) is not transient and is not retried.
            response = await self._request(
                "POST", "/api/chat", self.timeout, retries=DEFAULT_ATTEMPTS, json=body
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ProviderError(
                    f"Ollama has no model named {body['model']!r}.",
                    remedy=f"Install it with `ollama pull {body['model']}`.",
                ) from exc
            raise self._unreachable(exc) from exc
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc

        content = response.json().get("message", {}).get("content", "")
        if not content.strip():
            raise ProviderError(
                f"Ollama returned an empty response for model {body['model']!r}.",
                remedy="Try a larger model, or lower the temperature.",
            )
        return str(content).strip()

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature},
        }
        if max_tokens is not None:
            body["options"]["num_predict"] = max_tokens

        # Deliberately not retried: by the time a stream fails it has usually
        # yielded tokens the caller has already displayed, and starting over
        # would repeat them. ``complete`` is the retried path.
        try:
            async with self._get_client().stream(
                "POST", f"{self.base_url}/api/chat", json=body, timeout=self.timeout
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise self._unreachable(exc) from exc
