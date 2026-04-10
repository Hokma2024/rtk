from __future__ import annotations

import json
from typing import Any

import httpx

from common.metrics import llm_tokens_total

from .base import BaseLLMProvider, _llm_instrumentation


class OllamaProvider(BaseLLMProvider):
    def __init__(self, model: str, *, host: str | None = None) -> None:
        self.model = model
        from common.config import get_settings

        self.host = (host or get_settings().ollama_host).rstrip("/")

    def _parse_ndjson_last(self, text: str) -> dict[str, Any]:
        last_obj: dict[str, Any] | None = None
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
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        async with _llm_instrumentation("ollama", self.model) as ctx:
            url = f"{self.host}/api/chat"
            from common.config import get_settings

            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
            }
            think = get_settings().ollama_think
            if think is not None:
                payload["think"] = think
            if tools:
                payload["tools"] = tools

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                try:
                    data = resp.json()
                except ValueError:
                    data = self._parse_ndjson_last(resp.text)

            prompt_tokens = data.get("prompt_eval_count")
            completion_tokens = data.get("eval_count")
            if prompt_tokens is not None:
                llm_tokens_total.labels(provider="ollama", model=self.model, direction="input").inc(prompt_tokens)
            if completion_tokens is not None:
                llm_tokens_total.labels(provider="ollama", model=self.model, direction="output").inc(completion_tokens)

            msg = data.get("message") or {}
            content = msg.get("content") or ""
            raw_calls = msg.get("tool_calls") or []

            norm: list[dict[str, Any]] = []
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

            ctx["status"] = "ok"
            return content, norm
