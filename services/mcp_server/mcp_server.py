from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel
from mcp.server import FastMCP

from .models import *
from .services import OrderService, OtrsService

mcp = FastMCP("MCP Server")


def _to_json_text(obj: Any) -> str:
    """
    КРИТИЧНО: MCP должен отдавать JSON, а не repr(BaseModel) и не repr(dict).
    Поэтому возвращаем строку, которая является валидным JSON.
    """
    if isinstance(obj, BaseModel):
        return obj.model_dump_json() 
    try:
        return json.dumps(obj, ensure_ascii=False)
    except TypeError:
        return json.dumps(str(obj), ensure_ascii=False)


# =========================
# Orders
# =========================

@mcp.tool()
def search_logs(input: SearchLogsRequest) -> str:
    """Ищет код ошибки в логах заказа."""
    return _to_json_text(OrderService.search_logs(input))

@mcp.tool()
def get_order_status(input: GetOrderStatusRequest) -> str:
    """Возвращает статус заказа из БД СУЛЗ (mock)."""
    return _to_json_text(OrderService.get_order_status(input))

@mcp.tool()
def check_eissd_status(input: CheckEissdStatusRequest) -> str:
    """Проверяет статус заказа во внешней системе EISSD."""
    return _to_json_text(OrderService.check_eissd_status(input))

@mcp.tool()
def update_order_status(input: UpdateOrderStatusRequest) -> str:
    """Обновляет статус заказа."""
    return _to_json_text(OrderService.update_order_status(input))

@mcp.tool()
def check_edit_order_request(input: CheckEditOrderRequest) -> str:
    """Проверяет наличие заявки на редактирование."""
    return _to_json_text(CheckEditOrderResponse(has_edit_order=False, details={"order_id": input.order_id, "source": "mock"}))


# =========================
# OTRS
# =========================

@mcp.tool()
def resolve_mrf_queue(input: ResolveMrfQueueRequest) -> str:
    """Определяет очередь OTRS по региону."""
    return _to_json_text(OtrsService.resolve_mrf_queue(input))

@mcp.tool()
def add_otrs_comment(input: AddOtrsCommentRequest) -> str:
    """Добавляет комментарий к тикету."""
    return _to_json_text(OtrsService.add_comment(input))

@mcp.tool()
def list_otrs_comments(input: ListOtrsCommentsRequest) -> str:
    """Возвращает комментарии по тикету."""
    return _to_json_text(OtrsService.list_comments(input))

@mcp.tool()
def get_otrs_ticket(input: GetOtrsTicketRequest) -> str:
    """Возвращает данные тикета."""
    return _to_json_text(OtrsService.get_ticket(input))

@mcp.tool()
def update_otrs_ticket(input: UpdateOtrsTicketRequest) -> str:
    """Обновляет тикет OTRS."""
    return _to_json_text(OtrsService.update_ticket(input))


if __name__ == "__main__":
    mcp.run()