from __future__ import annotations

import json
from typing import Any

import httpx

from common.metrics import llm_tokens_total

from .base import BaseLLMProvider, _llm_instrumentation

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(BaseLLMProvider):
    def __init__(self, *, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("OpenRouterProvider requires LLM_API_KEY")
        self.api_key = api_key
        self.model = model

    async def acall(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        async with _llm_instrumentation("openrouter", self.model) as ctx:
            url = f"{_BASE_URL}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {"model": self.model, "messages": messages, "tools": tools, "temperature": 0}

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            usage = data.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            if prompt_tokens is not None:
                llm_tokens_total.labels(provider="openrouter", model=self.model, direction="input").inc(prompt_tokens)
            if completion_tokens is not None:
                llm_tokens_total.labels(provider="openrouter", model=self.model, direction="output").inc(
                    completion_tokens
                )

            choices = data.get("choices") or []
            if not choices:
                ctx["status"] = "ok"
                return "", []

            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls") or []

            norm: list[dict[str, Any]] = []
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

            ctx["status"] = "ok"
            return content, norm
