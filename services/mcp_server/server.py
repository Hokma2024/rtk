# tools.py
from mcp.server import FastMCP
from . import storage, model
from typing import Any

mcp = FastMCP("MCP Server")   # имя сервера

@mcp.tool()
def search_logs(order_id: str, pattern: str, window_days: int = 30) -> dict:
    """
    Ищет строки в логах заказа, содержащие заданный паттерн.
    Возвращает структуру, аналогичную SearchLogsResponse.
    """
    logs = storage.LOGS_DB.get(order_id, [])
    matched = [line for line in logs if pattern in line]
    if matched:
        return {"error_found": True, "error_code": pattern, "samples": matched}
    return {"error_found": False, "error_code": None, "samples": []}

@mcp.tool()
def check_eissd_status(order_id: str) -> dict:
    """Проверяет статус заказа в EISSD."""
    data = storage.EISSD_DB.get(order_id)
    if not data:
        raise ValueError(f"Order {order_id} not found in EISSD")   # MCP превратит это в ошибку
    return {"status": data["status"], "raw": data}

@mcp.tool()
def update_order_status(order_id: str, new_status: str) -> dict:
    """Обновляет статус заказа в ORDERS_DB."""
    record = storage.ORDERS_DB.get(order_id)
    if not record:
        storage.ORDERS_DB[order_id] = {"status": new_status, "comment": "created by mock"}
        return {"updated": True, "old_status": None, "new_status": new_status}
    old = record.get("status")
    record["status"] = new_status
    return {"updated": True, "old_status": old, "new_status": new_status}

@mcp.tool()
def resolve_mrf_queue(region: str = "COMMON") -> str:
    """Определяет очередь МРФ по региону."""
    region = (region or "COMMON").strip()
    return f"ОЦО.МРФ.Эксплуатация СУЛЗ.{region}"

@mcp.tool()
def add_otrs_comment(ticket_id: str, text: str) -> dict:
    """Добавляет комментарий к тикету OTRS."""
    storage.OTRS_COMMENTS.append({"ticket_id": ticket_id, "text": text})
    return {"ok": True}

@mcp.tool()
def check_edit_order_request(order_id: str) -> dict:
    """Проверяет наличие заявки на редактирование заказа (заглушка)."""
    return {"has_edit_order": False, "details": {"order_id": order_id, "source": "mock"}}

@mcp.tool()
def update_otrs_ticket(ticket_id: str, queue: str, status: str, assignee: Any = None) -> dict:
    """Обновляет данные тикета OTRS."""
    storage.OTRS_TICKETS[ticket_id] = {
        "ticket_id": ticket_id,
        "queue": queue,
        "status": status,
        "assignee": assignee,
    }
    return {"ok": True, "ticket": storage.OTRS_TICKETS[ticket_id]}


if __name__ == "__main__":
    mcp.run()
    print("Server start")