"""Ollama backend, over its HTTP API directly.

v1 reached Ollama through ``langchain_community.ChatOllama``, which meant a
~120 MB dependency tree — LangChain core, community, several serialisation
layers — for a single ``invoke()`` call against one JSON endpoint. This is
that endpoint.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from careercraft.errors import ProviderError
from careercraft.llm import ChatMessage
from careercraft.logging import get_logger

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

    def _make_client(self, timeout: float) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=timeout)

    async def _request(self, method: str, path: str, timeout: float, **kwargs: Any) -> Any:
        client = self._make_client(timeout)
        owns = self._client is None
        try:
            response = await client.request(method, f"{self.base_url}{path}", **kwargs)
            response.raise_for_status()
            return response
        finally:
            if owns:
                await client.aclose()

    async def is_available(self) -> bool:
        """True when the daemon answers. Never raises."""
        try:
            await self._request("GET", "/api/tags", _PROBE_TIMEOUT)
        except Exception:  # noqa: BLE001 - a probe that raises is a probe that lies
            return False
        return True

    async def list_models(self) -> list[str]:
        try:
            response = await self._request("GET", "/api/tags", _PROBE_TIMEOUT)
        except Exception:  # noqa: BLE001
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
            response = await self._request("POST", "/api/chat", self.timeout, json=body)
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

        client = self._make_client(self.timeout)
        owns = self._client is None
        try:
            async with client.stream(
                "POST", f"{self.base_url}/api/chat", json=body
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
        finally:
            if owns:
                await client.aclose()
