from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import httpx

from .base import BaseLLMProvider


class OpenRouterProvider(BaseLLMProvider):
    def __init__(self, *, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("OpenRouterProvider requires LLM_API_KEY")
        self.api_key = api_key
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1"

    async def acall(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        timeout: int,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages, "tools": tools, "temperature": 0}

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            return "", []

        msg = (choices[0] or {}).get("message") or {}
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        norm: List[Dict[str, Any]] = []
        for call in tool_calls:
            fn = call.get("function") if isinstance(call, dict) else None
            name = (fn or {}).get("name") if isinstance(fn, dict) else None
            args = (fn or {}).get("arguments") if isinstance(fn, dict) else None
            if name is None and isinstance(call, dict):
                name = call.get("name")
                args = call.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {}
            norm.append({"name": name, "arguments": args or {}})

        return content, norm
