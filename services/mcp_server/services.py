"""Бизнес-логика обработчиков MCP-инструментов."""

from __future__ import annotations

from . import storage
from .models import (
    AddOtrsCommentRequest,
    AddOtrsCommentResponse,
    CheckEissdStatusRequest,
    CheckEissdStatusResponse,
    GetOrderStatusRequest,
    GetOrderStatusResponse,
    GetOtrsTicketRequest,
    GetOtrsTicketResponse,
    ListOtrsCommentsRequest,
    ListOtrsCommentsResponse,
    MrfProcessTicketRequest,
    MrfProcessTicketResponse,
    OrderStatus,
    ResolveMrfQueueRequest,
    ResolveMrfQueueResponse,
    SearchLogsRequest,
    SearchLogsResponse,
    UpdateOrderStatusRequest,
    UpdateOrderStatusResponse,
    UpdateOtrsTicketRequest,
    UpdateOtrsTicketResponse,
)


class OrderService:
    @staticmethod
    def search_logs(data: SearchLogsRequest) -> SearchLogsResponse:
        logs = storage.LOGS_DB.get(data.order_id, [])
        matched = [line for line in logs if data.pattern in line]
        return SearchLogsResponse(
            error_found=bool(matched),
            error_code=data.pattern if matched else None,
            matched_samples=matched[:20],
            logs_full=list(logs),
        )

    @staticmethod
    def get_order_status(data: GetOrderStatusRequest) -> GetOrderStatusResponse:
        record = storage.ORDERS_DB.get(data.order_id)
        if not record:
            raise ValueError(f"Order {data.order_id} not found in ORDERS_DB")
        return GetOrderStatusResponse(
            status=OrderStatus(record["status"]),
            raw=record,
        )

    @staticmethod
    def check_eissd_status(data: CheckEissdStatusRequest) -> CheckEissdStatusResponse:
        record = storage.EISSD_DB.get(data.order_id)
        if not record:
            raise ValueError(f"Order {data.order_id} not found in EISSD")
        return CheckEissdStatusResponse(
            status=OrderStatus(record["status"]),
            raw=record,
        )

    @staticmethod
    def update_order_status(data: UpdateOrderStatusRequest) -> UpdateOrderStatusResponse:
        record = storage.ORDERS_DB.get(data.order_id)
        if not record:
            storage.ORDERS_DB[data.order_id] = {"status": data.new_status.value, "comment": "created by MCP"}
            return UpdateOrderStatusResponse(updated=True, new_status=data.new_status)

        old_status = OrderStatus(record["status"])
        record["status"] = data.new_status.value
        return UpdateOrderStatusResponse(updated=True, old_status=old_status, new_status=data.new_status)


class OtrsService:
    @staticmethod
    def resolve_mrf_queue(data: ResolveMrfQueueRequest) -> ResolveMrfQueueResponse:
        region = (data.region or "COMMON").upper()
        return ResolveMrfQueueResponse(queue=f"ОЦО.МРФ.Эксплуатация СУЛЗ.{region}")

    @staticmethod
    def add_comment(data: AddOtrsCommentRequest) -> AddOtrsCommentResponse:
        storage.OTRS_COMMENTS.append({"ticket_id": data.ticket_id, "text": data.text})
        return AddOtrsCommentResponse(ok=True)

    @staticmethod
    def list_comments(data: ListOtrsCommentsRequest) -> ListOtrsCommentsResponse:
        comments = [c for c in storage.OTRS_COMMENTS if c.get("ticket_id") == data.ticket_id]
        return ListOtrsCommentsResponse(comments=comments)

    @staticmethod
    def get_ticket(data: GetOtrsTicketRequest) -> GetOtrsTicketResponse:
        # При отсутствии записи возвращаем заглушку со статусом NEW
        t = storage.OTRS_TICKETS.get(data.ticket_id) or {
            "ticket_id": data.ticket_id,
            "queue": "",
            "status": "NEW",
            "assignee": None,
        }
        return GetOtrsTicketResponse(ticket=t)

    @staticmethod
    def mrf_process_ticket(data: MrfProcessTicketRequest) -> MrfProcessTicketResponse:
        from common.config import get_settings

        seed = get_settings().mrf_mock_seed
        verdicts = ["OK", "NEEDS_MANUAL", "EDIT_ORDER_PENDING", "ORDER_NOT_FOUND_IN_EISSD"]
        h = abs(hash((seed, data.order_id, (data.region or "COMMON").upper())))
        verdict = verdicts[h % len(verdicts)]

        queue = f"ОЦО.МРФ.Эксплуатация СУЛЗ.{(data.region or 'COMMON').upper()}"

        texts = {
            "OK": "МРФ: обработка завершена, статус синхронизирован.",
            "NEEDS_MANUAL": "МРФ: требуется ручная проверка специалистом.",
            "EDIT_ORDER_PENDING": "МРФ: обнаружена заявка на редактирование заказа.",
            "ORDER_NOT_FOUND_IN_EISSD": "МРФ: заказ отсутствует в ЕИССД.",
        }

        storage.OTRS_COMMENTS.append(
            {
                "ticket_id": data.ticket_id,
                "text": texts[verdict],
                "source": "mrf_mock",
            }
        )

        return MrfProcessTicketResponse(
            mrf_verdict=verdict,
            comment_added=True,
            queue=queue,
            details={"order_id": data.order_id, "region": (data.region or "COMMON").upper()},
        )

    @staticmethod
    def update_ticket(data: UpdateOtrsTicketRequest) -> UpdateOtrsTicketResponse:
        storage.OTRS_TICKETS[data.ticket_id] = {
            "ticket_id": data.ticket_id,
            "queue": data.queue,
            "status": data.status.value,
            "assignee": data.assignee,
        }
        return UpdateOtrsTicketResponse(ok=True, ticket=storage.OTRS_TICKETS[data.ticket_id])
