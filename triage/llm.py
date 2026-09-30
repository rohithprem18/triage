"""OpenAI-compatible chat client with tool calling (Sluice by default)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import httpx


class LLMError(Exception):
    pass


@dataclass
class Reply:
    message: dict
    model: str
    ms: float
    tokens: int = 0
    tool_calls: list[dict] = field(default_factory=list)


class LLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 90.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url, self.model = base_url.rstrip("/"), model
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        max_tokens: int = 900,
    ) -> Reply:
        body: dict = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        t = time.perf_counter()
        for attempt in range(4):
            try:
                r = await self._client.post(f"{self.base_url}/chat/completions", json=body)
            except httpx.HTTPError as e:
                if attempt == 3:
                    raise LLMError(f"LLM unreachable: {e.__class__.__name__}") from e
                await asyncio.sleep(2)
                continue
            if r.status_code in (429, 503) and attempt < 3:
                await asyncio.sleep(3 + 5 * attempt)
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json()["error"]["message"]
                except (ValueError, KeyError, TypeError):
                    msg = r.text[:200]
                raise LLMError(f"LLM error {r.status_code}: {msg}")
            data = r.json()
            msg = data["choices"][0]["message"]
            usage = data.get("usage") or {}
            return Reply(
                message=msg,
                model=(data.get("sluice") or {}).get("served_by") or data.get("model", ""),
                ms=(time.perf_counter() - t) * 1000,
                tokens=int(usage.get("total_tokens") or 0),
                tool_calls=msg.get("tool_calls") or [],
            )
        raise LLMError("LLM unavailable after retries")

    async def aclose(self) -> None:
        await self._client.aclose()
