from typing import List
from . import storage
from .models import *


class OrderService:

    @staticmethod
    def search_logs(data: SearchLogsRequest) -> SearchLogsResponse:
        logs = storage.LOGS_DB.get(data.order_id, [])
        matched = [line for line in logs if data.pattern in line]

        return SearchLogsResponse(
            error_found=bool(matched),
            error_code=data.pattern if matched else None,
            samples=matched[:20]  # ограничение для LLM
        )

    @staticmethod
    def check_eissd_status(
        data: CheckEissdStatusRequest
    ) -> CheckEissdStatusResponse:

        record = storage.EISSD_DB.get(data.order_id)
        if not record:
            raise ValueError(f"Order {data.order_id} not found in EISSD")

        return CheckEissdStatusResponse(
            status=OrderStatus(record["status"]),
            raw=record
        )

    @staticmethod
    def update_order_status(
        data: UpdateOrderStatusRequest
    ) -> UpdateOrderStatusResponse:

        record = storage.ORDERS_DB.get(data.order_id)

        if not record:
            storage.ORDERS_DB[data.order_id] = {
                "status": data.new_status.value,
                "comment": "created by MCP"
            }
            return UpdateOrderStatusResponse(
                updated=True,
                new_status=data.new_status
            )

        old_status = OrderStatus(record["status"])
        record["status"] = data.new_status.value

        return UpdateOrderStatusResponse(
            updated=True,
            old_status=old_status,
            new_status=data.new_status
        )


class OtrsService:

    @staticmethod
    def resolve_mrf_queue(
        data: ResolveMrfQueueRequest
    ) -> ResolveMrfQueueResponse:

        return ResolveMrfQueueResponse(
            queue=f"ОЦО.МРФ.Эксплуатация СУЛЗ.{data.region.value}"
        )

    @staticmethod
    def add_comment(
        data: AddOtrsCommentRequest
    ) -> AddOtrsCommentResponse:

        storage.OTRS_COMMENTS.append({
            "ticket_id": data.ticket_id,
            "text": data.text
        })
        return AddOtrsCommentResponse(ok=True)

    @staticmethod
    def update_ticket(
        data: UpdateOtrsTicketRequest
    ) -> UpdateOtrsTicketResponse:

        storage.OTRS_TICKETS[data.ticket_id] = {
            "ticket_id": data.ticket_id,
            "queue": data.queue,
            "status": data.status.value,
            "assignee": data.assignee
        }

        return UpdateOtrsTicketResponse(
            ok=True,
            ticket=storage.OTRS_TICKETS[data.ticket_id]
        )