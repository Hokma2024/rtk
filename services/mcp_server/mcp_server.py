"""MCP-сервер, предоставляющий инструменты для работы с заказами и OTRS."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import FastMCP
from pydantic import BaseModel

from common.logging import configure_logging, get_logger
from common.metrics import mcp_requests_total

from .models import (
    AddOtrsCommentRequest,
    CheckEditOrderRequest,
    CheckEditOrderResponse,
    CheckEissdStatusRequest,
    GetOrderStatusRequest,
    GetOtrsTicketRequest,
    ListOtrsCommentsRequest,
    MrfProcessTicketRequest,
    ResolveMrfQueueRequest,
    SearchLogsRequest,
    UpdateOrderStatusRequest,
    UpdateOtrsTicketRequest,
)
from .services import OrderService, OtrsService

configure_logging("mcp_server")
log = get_logger(__name__)

mcp = FastMCP("MCP Server")


def _to_json_text(obj: Any) -> str:
    """Сериализует *obj* в JSON-строку; MCP-инструменты обязаны возвращать валидный JSON."""
    if isinstance(obj, BaseModel):
        return obj.model_dump_json()
    try:
        return json.dumps(obj, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(obj), ensure_ascii=False)


# =========================
# Заказы
# =========================


@mcp.tool()
def search_logs(input: SearchLogsRequest) -> str:
    """Ищет в логах заказа шаблон ошибки."""
    try:
        result = _to_json_text(OrderService.search_logs(input))
        mcp_requests_total.labels(tool="search_logs", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="search_logs")
        mcp_requests_total.labels(tool="search_logs", status="error").inc()
        raise


@mcp.tool()
def get_order_status(input: GetOrderStatusRequest) -> str:
    """Возвращает статус заказа из мок-БД СУЛЗ."""
    try:
        result = _to_json_text(OrderService.get_order_status(input))
        mcp_requests_total.labels(tool="get_order_status", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="get_order_status")
        mcp_requests_total.labels(tool="get_order_status", status="error").inc()
        raise


@mcp.tool()
def check_eissd_status(input: CheckEissdStatusRequest) -> str:
    """Проверяет статус заказа во внешней системе ЕИССД."""
    try:
        result = _to_json_text(OrderService.check_eissd_status(input))
        mcp_requests_total.labels(tool="check_eissd_status", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="check_eissd_status")
        mcp_requests_total.labels(tool="check_eissd_status", status="error").inc()
        raise


@mcp.tool()
def update_order_status(input: UpdateOrderStatusRequest) -> str:
    """Обновляет статус заказа."""
    try:
        result = _to_json_text(OrderService.update_order_status(input))
        mcp_requests_total.labels(tool="update_order_status", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="update_order_status")
        mcp_requests_total.labels(tool="update_order_status", status="error").inc()
        raise


@mcp.tool()
def check_edit_order_request(input: CheckEditOrderRequest) -> str:
    """Проверяет наличие заявки на редактирование заказа."""
    try:
        result = _to_json_text(
            CheckEditOrderResponse(
                has_edit_order=False,
                details={"order_id": input.order_id, "source": "mock"},
            )
        )
        mcp_requests_total.labels(tool="check_edit_order_request", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="check_edit_order_request")
        mcp_requests_total.labels(tool="check_edit_order_request", status="error").inc()
        raise


# =========================
# OTRS
# =========================


@mcp.tool()
def resolve_mrf_queue(input: ResolveMrfQueueRequest) -> str:
    """Определяет очередь OTRS для региона."""
    try:
        result = _to_json_text(OtrsService.resolve_mrf_queue(input))
        mcp_requests_total.labels(tool="resolve_mrf_queue", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="resolve_mrf_queue")
        mcp_requests_total.labels(tool="resolve_mrf_queue", status="error").inc()
        raise


@mcp.tool()
def mrf_process_ticket(input: MrfProcessTicketRequest) -> str:
    """Эмулирует синхронный цикл обработки тикета очередью МРФ: возвращает вердикт и добавляет комментарий от МРФ."""
    try:
        result = _to_json_text(OtrsService.mrf_process_ticket(input))
        mcp_requests_total.labels(tool="mrf_process_ticket", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="mrf_process_ticket")
        mcp_requests_total.labels(tool="mrf_process_ticket", status="error").inc()
        raise


@mcp.tool()
def add_otrs_comment(input: AddOtrsCommentRequest) -> str:
    """Добавляет комментарий к тикету OTRS."""
    try:
        result = _to_json_text(OtrsService.add_comment(input))
        mcp_requests_total.labels(tool="add_otrs_comment", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="add_otrs_comment")
        mcp_requests_total.labels(tool="add_otrs_comment", status="error").inc()
        raise


@mcp.tool()
def list_otrs_comments(input: ListOtrsCommentsRequest) -> str:
    """Возвращает комментарии тикета OTRS."""
    try:
        result = _to_json_text(OtrsService.list_comments(input))
        mcp_requests_total.labels(tool="list_otrs_comments", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="list_otrs_comments")
        mcp_requests_total.labels(tool="list_otrs_comments", status="error").inc()
        raise


@mcp.tool()
def get_otrs_ticket(input: GetOtrsTicketRequest) -> str:
    """Возвращает данные тикета OTRS."""
    try:
        result = _to_json_text(OtrsService.get_ticket(input))
        mcp_requests_total.labels(tool="get_otrs_ticket", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="get_otrs_ticket")
        mcp_requests_total.labels(tool="get_otrs_ticket", status="error").inc()
        raise


@mcp.tool()
def update_otrs_ticket(input: UpdateOtrsTicketRequest) -> str:
    """Обновляет тикет OTRS."""
    try:
        result = _to_json_text(OtrsService.update_ticket(input))
        mcp_requests_total.labels(tool="update_otrs_ticket", status="ok").inc()
        return result
    except Exception:
        log.exception("mcp_tool_error", tool="update_otrs_ticket")
        mcp_requests_total.labels(tool="update_otrs_ticket", status="error").inc()
        raise


if __name__ == "__main__":
    mcp.run()
