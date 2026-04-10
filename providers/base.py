"""Базовый контракт LLM-провайдера и общая инструментация."""

from __future__ import annotations

import abc
import contextlib
import time
from collections.abc import AsyncGenerator
from typing import Any

from common.logging import get_logger
from common.metrics import llm_request_duration_seconds, llm_requests_total

log = get_logger(__name__)


@contextlib.asynccontextmanager
async def _llm_instrumentation(provider: str, model: str) -> AsyncGenerator[dict[str, Any], None]:
    """Асинхронный контекстный менеджер: логирует и снимает метрики вокруг вызова LLM.

    Отдаёт мутабельный словарь ``ctx``; при успехе нужно выставить ``ctx["status"] = "ok"``.
    """
    start = time.perf_counter()
    ctx: dict[str, Any] = {"status": "error"}
    log.info("llm_call_start", provider=provider, model=model)
    try:
        yield ctx
    except Exception:
        log.exception("llm_call_failed", provider=provider, model=model)
        raise
    finally:
        elapsed = time.perf_counter() - start
        llm_requests_total.labels(provider=provider, model=model, status=ctx["status"]).inc()
        llm_request_duration_seconds.labels(provider=provider, model=model).observe(elapsed)
        log.info(
            "llm_call_end",
            provider=provider,
            model=model,
            status=ctx["status"],
            duration_ms=round(elapsed * 1000),
        )


class BaseLLMProvider(abc.ABC):
    @abc.abstractmethod
    async def acall(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        timeout: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        raise NotImplementedError
