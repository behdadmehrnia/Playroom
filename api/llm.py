from __future__ import annotations

from typing import Any

import httpx

from api.core import LLMCompletionRequest, extract_text_from_completion


class LLMError(RuntimeError):
    """Raised when the backing LLM provider returns an error or bad payload."""


class OpenAICompatibleLLMClient:
    """Async LLM client implementing ``api.core.LLMClient`` over httpx."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_sec: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key.strip()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_sec)

    async def complete(self, request: LLMCompletionRequest) -> str:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            # Completions are always non-streaming; the API simulates streaming itself.
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        url = f"{self._base_url}/chat/completions"
        try:
            response = await self._client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"LLM HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("LLM response was not valid JSON") from exc

        return extract_text_from_completion(data)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
