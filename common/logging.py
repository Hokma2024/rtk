"""Структурированное JSON-логирование для всех сервисов RTKI.

Все модули получают логгер через `get_logger(__name__)`. Каждый сервис
один раз при старте вызывает `configure_logging(service_name)`. Trace ID
пробрасываются через contextvars, поэтому все последующие вызовы логов
автоматически включают их без передачи параметра через все функции.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
_configured: bool = False


def _add_trace_id(_logger, _method, event_dict):
    tid = _trace_id_var.get()
    if tid is not None:
        event_dict["trace_id"] = tid
    return event_dict


def configure_logging(service_name: str, level: str = "INFO") -> None:
    global _configured
    if _configured:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        stream=sys.stdout,
        level=log_level,
        format="%(message)s",
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace_id,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(service=service_name)
    _configured = True


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


def get_or_create_trace_id(header_value: str | None) -> str:
    if header_value:
        try:
            uuid.UUID(header_value)
            return header_value
        except ValueError:
            pass
    return str(uuid.uuid4())


def bind_trace_id(trace_id: str) -> None:
    _trace_id_var.set(trace_id)


def clear_trace_id() -> None:
    _trace_id_var.set(None)
