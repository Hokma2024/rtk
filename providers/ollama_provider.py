from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Tuple

import httpx

from .base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    def __init__(self, model: str, *, host: str | None = None) -> None:
        self.model = model
        host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.host = host.rstrip("/")

    def _parse_ndjson_last(self, text: str) -> Dict[str, Any]:
        last_obj: Dict[str, Any] | None = None
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                last_obj = json.loads(line)
            except json.JSONDecodeError:
                continue
        if last_obj is None:
            raise RuntimeError("Ollama returned non-JSON response")
        return last_obj

    async def acall(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        timeout: int,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        url = f"{self.host}/api/chat"
        payload: Dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                data = self._parse_ndjson_last(resp.text)

        msg = data.get("message") or {}
        content = msg.get("content") or ""
        raw_calls = msg.get("tool_calls") or []

        norm: List[Dict[str, Any]] = []
        for call in raw_calls:
            fn = call.get("function") if isinstance(call, dict) else None
            name = (fn or {}).get("name") if isinstance(fn, dict) else None
            args = (fn or {}).get("arguments") if isinstance(fn, dict) else None
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {}
            norm.append({"name": name, "arguments": args or {}, "raw": call})

        return content, norm