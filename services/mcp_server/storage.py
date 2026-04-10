"""Мок-хранилище в памяти для данных заказов, ЕИССД и OTRS."""

from __future__ import annotations

from typing import Any

def _denied_log(order_id: str, ts: str, ext: str = "44") -> str:
    """Шаблонная строка лога СУЛЗ с ошибкой ORDER_STATUS_DENIED."""
    return (
        f"{ts} [http-nio-8080-exec-13] INFO r.r.s.o.c.c.LoggingFilter: "
        f'Request POST /orders/close: <request orderId="{order_id}" '
        f'orderStatus="ORDER_STATUS_DENIED" '
        f'orderStatusDateTime="{ts.split(" ")[0]}T05:37:53+03:00" '
        f'orderStatusExt="{ext}" reqType="SET_ORDER_STATUS"/>'
    )


LOGS_DB: dict[str, list[str]] = {
    # Исходные записи (smoke-кейсы)
    "1800003902272": [_denied_log("1800003902272", "2025-09-02 02:37:54.156")],
    "1800003879400": [
        "2025-09-10 11:10:10.010 INFO some.logger: Request POST "
        '/orders/close: <request orderId="1800003879400" orderStatus="OK"/>',
    ],

    # --- Реальные тестовые тикеты (тикеты.txt) ---
    # №1 «Серийные номера проданы ранее» (Юг) — основная и связанная заявка
    "1800003858739": [_denied_log("1800003858739", "2025-10-15 09:12:33.201", ext="21")],
    "1800003855055": [_denied_log("1800003855055", "2025-10-14 18:04:11.004", ext="21")],
    # №2 «Не переданы в доставку» (Москва и МО)
    "1800003979077": [_denied_log("1800003979077", "2025-11-02 07:45:01.770", ext="55")],
    # №3 «Нет конечного статуса» (Центр)
    "1800003939728": [_denied_log("1800003939728", "2025-10-28 12:22:19.728", ext="12")],
    # №4 «Серийный номер был продан ранее» (Северо-Запад)
    "1800003897269": [_denied_log("1800003897269", "2025-10-20 14:33:50.269", ext="21")],
    "1800003897516": [_denied_log("1800003897516", "2025-10-20 14:34:15.516", ext="21")],
    # №5 «Ошибка обработки заявки в ИС МРФ после доставки» (Юг)
    "1800003910917": [_denied_log("1800003910917", "2025-10-22 16:10:05.917", ext="77")],
    # №6 «Ошибка списания оборудования в CPE» (Дальний Восток)
    "1800003981610": [_denied_log("1800003981610", "2025-11-03 03:18:42.610", ext="88")],
    # №7 канонический ORDER_STATUS_DENIED (Юг)
    "1800003879409": [_denied_log("1800003879409", "2025-10-18 05:37:53.409", ext="44")],
}

# СУЛЗ (мок): статусы и комментарии
ORDERS_DB: dict[str, dict[str, Any]] = {
    "1800003902272": {"status": "DENIED", "comment": "Initial mock status"},
    "1800003879400": {"status": "DENIED", "comment": "Initial mock status"},

    "1800003858739": {"status": "DENIED", "comment": "Серийные номера проданы ранее"},
    "1800003855055": {"status": "DENIED", "comment": "Связанная заявка: требуется перевод в отказ"},
    "1800003979077": {"status": "DENIED", "comment": "Не переданы в доставку"},
    "1800003939728": {"status": "DENIED", "comment": "Нет конечного статуса"},
    "1800003897269": {"status": "DENIED", "comment": "Серийный номер был продан ранее"},
    "1800003897516": {"status": "DENIED", "comment": "Ожидается замена серийника в ЕИССД"},
    "1800003910917": {"status": "DENIED", "comment": "Ошибка обработки в ИС МРФ после доставки"},
    "1800003981610": {"status": "DENIED", "comment": "Ошибка списания оборудования в CPE"},
    "1800003879409": {"status": "DENIED", "comment": "Ошибка ORDER_STATUS_DENIED"},
}

# ЕИССД (мок): статусы во внешней системе
EISSD_DB: dict[str, dict[str, Any]] = {
    "1800003902272": {"status": "IN_PROGRESS"},
    "1800003879400": {"status": "IN_PROGRESS"},

    "1800003858739": {"status": "IN_PROGRESS"},
    "1800003855055": {"status": "IN_PROGRESS"},
    "1800003979077": {"status": "NOT_DELIVERED"},
    "1800003939728": {"status": "NO_FINAL_STATUS"},
    "1800003897269": {"status": "IN_PROGRESS"},
    "1800003897516": {"status": "IN_PROGRESS"},
    "1800003910917": {"status": "MRF_ERROR"},
    "1800003981610": {"status": "CPE_WRITEOFF_ERROR"},
    "1800003879409": {"status": "IN_PROGRESS"},
}

# OTRS (мок)
OTRS_COMMENTS: list[dict[str, Any]] = []
OTRS_TICKETS: dict[str, dict[str, Any]] = {}
