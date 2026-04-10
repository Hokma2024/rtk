"""unified_rtk.common.models

Общие доменные модели и вспомогательные функции нормализации.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class OrderStatus(str, enum.Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    DENIED = "DENIED"
    FAILED = "FAILED"


class OtrsStatus(str, enum.Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


ORDER_STATUS_ALIASES: dict[str, OrderStatus] = {
    "created": OrderStatus.CREATED,
    "in_progress": OrderStatus.IN_PROGRESS,
    "in progress": OrderStatus.IN_PROGRESS,
    "processing": OrderStatus.IN_PROGRESS,
    "done": OrderStatus.DONE,
    "completed": OrderStatus.DONE,
    "denied": OrderStatus.DENIED,
    "order_status_denied": OrderStatus.DENIED,
    "failed": OrderStatus.FAILED,
    "CREATED": OrderStatus.CREATED,
    "IN_PROGRESS": OrderStatus.IN_PROGRESS,
    "DONE": OrderStatus.DONE,
    "DENIED": OrderStatus.DENIED,
    "FAILED": OrderStatus.FAILED,
}

OTRS_STATUS_ALIASES: dict[str, OtrsStatus] = {
    "new": OtrsStatus.NEW,
    "open": OtrsStatus.OPEN,
    "in_work": OtrsStatus.OPEN,
    "in work": OtrsStatus.OPEN,
    "closed": OtrsStatus.CLOSED,
    "NEW": OtrsStatus.NEW,
    "OPEN": OtrsStatus.OPEN,
    "CLOSED": OtrsStatus.CLOSED,
}


def normalize_order_status(value: str) -> OrderStatus:
    """Возвращает OrderStatus для переданной строки; бросает ValueError, если значение не распознано."""
    key = (value or "").strip()
    if key in ORDER_STATUS_ALIASES:
        return ORDER_STATUS_ALIASES[key]
    low = key.lower()
    if low in ORDER_STATUS_ALIASES:
        return ORDER_STATUS_ALIASES[low]
    raise ValueError(f"Unrecognised order status: {value}")


def normalize_otrs_status(value: str) -> OtrsStatus:
    """Возвращает OtrsStatus для переданной строки; бросает ValueError, если значение не распознано."""
    key = (value or "").strip()
    if key in OTRS_STATUS_ALIASES:
        return OTRS_STATUS_ALIASES[key]
    low = key.lower()
    if low in OTRS_STATUS_ALIASES:
        return OTRS_STATUS_ALIASES[low]
    raise ValueError(f"Unrecognised OTRS status: {value}")


@dataclass
class ActionLogEntry:
    tool: str
    params: dict[str, Any]
    started_at: datetime = field(default_factory=datetime.utcnow)
    duration_ms: int | None = None
    ok: bool = True
    error: str | None = None
    error_type: str | None = None
    result: Any = None


@dataclass
class Ticket:
    id: str
    order_id: str
    subject: str
    annotation: str
    description: str
    region: str
    queue: str | None
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
