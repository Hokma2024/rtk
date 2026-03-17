"""
unified_rtk.common.config

Единая конфигурация: всё из env/.env через Pydantic.
"""

from __future__ import annotations

import functools
import logging
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # MCP
    mcp_server_module: str = Field(
        "services.mcp_server.mcp_server",
        env="MCP_SERVER_MODULE",
    )

    # RAG (HTTP)
    rag_base_url: Optional[str] = Field(None, env="RAG_BASE_URL")

    # LLM
    llm_provider: str = Field("openrouter", env="LLM_PROVIDER")  # openrouter|ollama
    llm_model_name: str = Field("qwen2.5:7b-instruct", env="LLM_MODEL_NAME")
    llm_api_key: Optional[str] = Field(None, env="LLM_API_KEY")

    # tools|json|fallback
    llm_mode: str = Field("tools", env="LLM_MODE")

    llm_max_iterations: int = Field(6, env="LLM_MAX_ITERATIONS")
    llm_timeout_seconds: int = Field(30, env="LLM_TIMEOUT_SECONDS")

    request_time_budget_seconds: int = Field(90, env="REQUEST_TIME_BUDGET_SECONDS")

    # Финализация
    allow_queue_change: bool = Field(False, env="ALLOW_QUEUE_CHANGE")

    # API / debug
    debug: bool = Field(False, env="DEBUG")
    mcp_debug: bool = Field(False, env="MCP_DEBUG")
    ollama_host: str = Field("http://localhost:11434", env="OLLAMA_HOST")
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@functools.lru_cache()
def get_settings() -> Settings:
    s = Settings()
    
    logger.info(
        "[CONFIG_LOADED] llm_provider=%s llm_model=%s llm_mode=%s timeout=%d rag_url=%s",
        s.llm_provider,
        s.llm_model_name,
        s.llm_mode,
        s.llm_timeout_seconds,
        s.rag_base_url or "none"
    )
    
    original_mode = s.llm_mode
    s.llm_mode = (s.llm_mode or "tools").strip().lower()
    if s.llm_mode not in ("tools", "json", "fallback"):
        logger.warning(
            "[CONFIG_WARN] llm_mode_invalid original=%s fallback=tools",
            original_mode
        )
        s.llm_mode = "tools"
    
    return s
