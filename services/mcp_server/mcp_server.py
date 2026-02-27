from mcp.server import FastMCP
from .models import *
from .services import OrderService, OtrsService

mcp = FastMCP("MCP Server")


# =========================
# Orders
# =========================

@mcp.tool()
def search_logs(input: SearchLogsRequest) -> SearchLogsResponse:
    """Ищет код ошибки в логах заказа."""
    return OrderService.search_logs(input)


@mcp.tool()
def check_eissd_status(
    input: CheckEissdStatusRequest
) -> CheckEissdStatusResponse:
    """Проверяет статус заказа во внешней системе EISSD."""
    return OrderService.check_eissd_status(input)


@mcp.tool()
def update_order_status(
    input: UpdateOrderStatusRequest
) -> UpdateOrderStatusResponse:
    """Обновляет статус заказа."""
    return OrderService.update_order_status(input)


@mcp.tool()
def check_edit_order_request(
    input: CheckEditOrderRequest
) -> CheckEditOrderResponse:
    """Проверяет наличие заявки на редактирование."""
    return CheckEditOrderResponse(
        has_edit_order=False,
        details={"order_id": input.order_id, "source": "mock"}
    )


# =========================
# OTRS
# =========================

@mcp.tool()
def resolve_mrf_queue(
    input: ResolveMrfQueueRequest
) -> ResolveMrfQueueResponse:
    """Определяет очередь OTRS по региону."""
    return OtrsService.resolve_mrf_queue(input)


@mcp.tool()
def add_otrs_comment(
    input: AddOtrsCommentRequest
) -> AddOtrsCommentResponse:
    """Добавляет комментарий к тикету."""
    return OtrsService.add_comment(input)


@mcp.tool()
def update_otrs_ticket(
    input: UpdateOtrsTicketRequest
) -> UpdateOtrsTicketResponse:
    """Обновляет тикет OTRS."""
    return OtrsService.update_ticket(input)


if __name__ == "__main__":
    mcp.run()