from __future__ import annotations

import pytest

from providers import get_provider
from providers.base import BaseLLMProvider
from providers.ollama_provider import OllamaProvider
from providers.openrouter_provider import OpenRouterProvider


class TestProvidersFactory:
    @pytest.mark.unit
    def test_get_provider_ollama_returns_instance(self):
        provider = get_provider("ollama", model="llama3")
        assert isinstance(provider, OllamaProvider)
        assert isinstance(provider, BaseLLMProvider)

    @pytest.mark.unit
    def test_get_provider_openrouter_returns_instance(self):
        provider = get_provider("openrouter", api_key="dummy-key", model="gpt-4o")
        assert isinstance(provider, OpenRouterProvider)
        assert isinstance(provider, BaseLLMProvider)

    @pytest.mark.unit
    def test_get_provider_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider("nonexistent")

    @pytest.mark.unit
    def test_ollama_provider_host_defaults(self):
        p = OllamaProvider(model="mistral")
        assert "11434" in p.host or "localhost" in p.host

    @pytest.mark.unit
    def test_ollama_provider_model_set(self):
        p = OllamaProvider(model="phi3")
        assert p.model == "phi3"
