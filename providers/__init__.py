from __future__ import annotations

from .base import BaseLLMProvider


def get_provider(name: str, *, api_key: str | None = None, model: str = "") -> BaseLLMProvider:
    name = (name or "").lower()
    if name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(model=model)
    if name == "openrouter":
        from .openrouter_provider import OpenRouterProvider
        return OpenRouterProvider(api_key=api_key, model=model)
    raise ValueError(f"Unknown LLM provider: {name}")
