"""
unified_rtk.common.config

Единая конфигурация: всё из env/.env через Pydantic.
"""

from __future__ import annotations

import functools
import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # MCP
    mcp_server_module: str = "services.mcp_server.mcp_server"

    # RAG (HTTP)
    rag_base_url: str | None = None

    # LLM
    llm_provider: str = "openrouter"  # openrouter|ollama
    llm_model_name: str = "qwen2.5:7b-instruct"
    llm_api_key: str | None = None

    # tools|json|fallback
    llm_mode: str = "tools"

    llm_max_iterations: int = 6
    llm_timeout_seconds: int = 30

    request_time_budget_seconds: int = 90

    # Финализация
    allow_queue_change: bool = False

    # LLM safety net / agent loop
    llm_max_steps: int = 12
    llm_max_tool_errors: int = 3

    # Verify recheck
    verify_recheck_window_days: int = 1

    # MRF mock
    mrf_mock_seed: int = 0

    # API / debug
    debug: bool = False
    mcp_debug: bool = False
    ollama_host: str = "http://localhost:11434"
    ollama_think: bool | None = None


@functools.lru_cache
def get_settings() -> Settings:
    s = Settings()

    logger.info(
        "[CONFIG_LOADED] llm_provider=%s llm_model=%s llm_mode=%s timeout=%d rag_url=%s",
        s.llm_provider,
        s.llm_model_name,
        s.llm_mode,
        s.llm_timeout_seconds,
        s.rag_base_url or "none",
    )

    original_mode = s.llm_mode
    s.llm_mode = (s.llm_mode or "tools").strip().lower()
    if s.llm_mode not in ("tools", "json", "fallback"):
        logger.warning(
            "[CONFIG_WARN] llm_mode_invalid original=%s fallback=tools",
            original_mode,
        )
        s.llm_mode = "tools"

    return s
