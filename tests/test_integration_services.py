"""Интеграционные тесты взаимодействия сервисов (без моков)."""

from __future__ import annotations

import pytest

from services.mcp_server import storage
from services.mcp_server.models import (
    AddOtrsCommentRequest,
    CheckEissdStatusRequest,
    GetOrderStatusRequest,
    GetOtrsTicketRequest,
    ListOtrsCommentsRequest,
    MrfProcessTicketRequest,
    OrderStatus,
    OtrsStatus,
    ResolveMrfQueueRequest,
    SearchLogsRequest,
    UpdateOrderStatusRequest,
    UpdateOtrsTicketRequest,
)
from services.mcp_server.services import OrderService, OtrsService


class TestCrossServiceWorkflow:
    @pytest.mark.integration
    def test_denied_order_workflow(self):
        order_id = "1800003902272"

        search = OrderService.search_logs(SearchLogsRequest(order_id=order_id, pattern="ORDER_STATUS_DENIED"))
        assert search.error_found is True

        status = OrderService.get_order_status(GetOrderStatusRequest(order_id=order_id))
        assert status.status == OrderStatus.DENIED

        eissd = OrderService.check_eissd_status(CheckEissdStatusRequest(order_id=order_id))
        assert eissd.status == OrderStatus.IN_PROGRESS

        update = OrderService.update_order_status(
            UpdateOrderStatusRequest(order_id=order_id, new_status=OrderStatus.IN_PROGRESS)
        )
        assert update.updated is True
        assert update.old_status == OrderStatus.DENIED

        new_status = OrderService.get_order_status(GetOrderStatusRequest(order_id=order_id))
        assert new_status.status == OrderStatus.IN_PROGRESS

    @pytest.mark.integration
    def test_otrs_ticket_lifecycle(self):
        ticket_id = "TKT-INT-001"

        t = OtrsService.get_ticket(GetOtrsTicketRequest(ticket_id=ticket_id))
        assert t.ticket["status"] == "NEW"

        q = OtrsService.resolve_mrf_queue(ResolveMrfQueueRequest(region="MSK"))
        assert q.queue

        OtrsService.update_ticket(
            UpdateOtrsTicketRequest(
                ticket_id=ticket_id,
                queue=q.queue,
                status=OtrsStatus.OPEN,
            )
        )

        OtrsService.add_comment(AddOtrsCommentRequest(ticket_id=ticket_id, text="Processed by integration test"))

        t2 = OtrsService.get_ticket(GetOtrsTicketRequest(ticket_id=ticket_id))
        assert t2.ticket["status"] == "OPEN"
        assert t2.ticket["queue"] == q.queue

        comments = OtrsService.list_comments(ListOtrsCommentsRequest(ticket_id=ticket_id))
        assert any("integration test" in c.get("text", "") for c in comments.comments)


class TestStorageIsolation:
    @pytest.mark.integration
    def test_modify_storage(self):
        storage.ORDERS_DB["TEMP_ORDER"] = {"status": "CREATED", "comment": "temp"}
        assert "TEMP_ORDER" in storage.ORDERS_DB

    @pytest.mark.integration
    def test_verify_clean_storage(self):
        assert "TEMP_ORDER" not in storage.ORDERS_DB


class TestMultiOrderOperations:
    @pytest.mark.integration
    def test_batch_status_check(self):
        orders = ["1800003902272", "1800003879400"]
        results = {}
        for oid in orders:
            try:
                resp = OrderService.get_order_status(GetOrderStatusRequest(order_id=oid))
                results[oid] = resp.status.value
            except ValueError:
                results[oid] = "NOT_FOUND"

        assert results["1800003902272"] == "DENIED"
        assert results["1800003879400"] == "DENIED"

    @pytest.mark.integration
    def test_update_preserves_other_orders(self):
        OrderService.update_order_status(
            UpdateOrderStatusRequest(order_id="1800003902272", new_status=OrderStatus.DONE)
        )
        other = OrderService.get_order_status(GetOrderStatusRequest(order_id="1800003879400"))
        assert other.status == OrderStatus.DENIED


class TestMrfProcessTicketIntegration:
    @pytest.mark.integration
    def test_mrf_process_ticket_verdict_and_comment(self):
        resp = OtrsService.mrf_process_ticket(
            MrfProcessTicketRequest(ticket_id="TKT-INT-1", order_id="1800003902272", region="MSK")
        )
        assert resp.mrf_verdict in {"OK", "NEEDS_MANUAL", "EDIT_ORDER_PENDING", "ORDER_NOT_FOUND_IN_EISSD"}
        assert resp.comment_added is True
        assert "MSK" in resp.queue

    @pytest.mark.integration
    def test_mrf_process_ticket_comment_recorded(self):
        OtrsService.mrf_process_ticket(
            MrfProcessTicketRequest(ticket_id="TKT-INT-2", order_id="1800003902272", region="MSK")
        )
        comments = OtrsService.list_comments(ListOtrsCommentsRequest(ticket_id="TKT-INT-2"))
        assert any(c.get("source") == "mrf_mock" for c in comments.comments)
