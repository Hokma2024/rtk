"""Юнит-тесты доменных моделей и бизнес-логики."""

from __future__ import annotations

from datetime import datetime

import pytest

from common.models import (
    ActionLogEntry,
    OrderStatus,
    OtrsStatus,
    Ticket,
    normalize_order_status,
    normalize_otrs_status,
)
from services.mcp_server import storage
from services.mcp_server.models import (
    AddOtrsCommentRequest,
    CheckEissdStatusRequest,
    GetOrderStatusRequest,
    GetOtrsTicketRequest,
    ListOtrsCommentsRequest,
    Region,
    ResolveMrfQueueRequest,
    SearchLogsRequest,
    UpdateOrderStatusRequest,
    UpdateOtrsTicketRequest,
)
from services.mcp_server.services import OrderService, OtrsService


class TestNormalizeOrderStatus:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("CREATED", OrderStatus.CREATED),
            ("created", OrderStatus.CREATED),
            ("IN_PROGRESS", OrderStatus.IN_PROGRESS),
            ("in_progress", OrderStatus.IN_PROGRESS),
            ("in progress", OrderStatus.IN_PROGRESS),
            ("processing", OrderStatus.IN_PROGRESS),
            ("DONE", OrderStatus.DONE),
            ("done", OrderStatus.DONE),
            ("completed", OrderStatus.DONE),
            ("DENIED", OrderStatus.DENIED),
            ("denied", OrderStatus.DENIED),
            ("order_status_denied", OrderStatus.DENIED),
            ("FAILED", OrderStatus.FAILED),
            ("failed", OrderStatus.FAILED),
        ],
    )
    def test_known_values(self, raw, expected):
        assert normalize_order_status(raw) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize("raw", ["", "UNKNOWN", "random", None])
    def test_unknown_raises(self, raw):
        with pytest.raises(ValueError, match="Unrecognised order status"):
            normalize_order_status(raw)

    @pytest.mark.unit
    def test_whitespace_handling(self):
        assert normalize_order_status("  DONE  ") == OrderStatus.DONE


class TestNormalizeOtrsStatus:
    @pytest.mark.unit
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("NEW", OtrsStatus.NEW),
            ("new", OtrsStatus.NEW),
            ("OPEN", OtrsStatus.OPEN),
            ("open", OtrsStatus.OPEN),
            ("in_work", OtrsStatus.OPEN),
            ("in work", OtrsStatus.OPEN),
            ("CLOSED", OtrsStatus.CLOSED),
            ("closed", OtrsStatus.CLOSED),
        ],
    )
    def test_known_values(self, raw, expected):
        assert normalize_otrs_status(raw) == expected

    @pytest.mark.unit
    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unrecognised OTRS status"):
            normalize_otrs_status("INVALID")


class TestTicketDataclass:
    @pytest.mark.unit
    def test_construction(self, sample_ticket):
        assert sample_ticket.id == "TKT-001"
        assert sample_ticket.order_id == "1800003902272"
        assert sample_ticket.region == "MSK"
        assert isinstance(sample_ticket.metadata, dict)

    @pytest.mark.unit
    def test_default_metadata(self):
        t = Ticket(
            id="X",
            order_id="Y",
            subject="",
            annotation="",
            description="",
            region="",
            queue=None,
            created_at=datetime.utcnow(),
        )
        assert t.metadata == {}


class TestActionLogEntry:
    @pytest.mark.unit
    def test_defaults(self):
        entry = ActionLogEntry(tool="test_tool", params={"a": 1})
        assert entry.ok is True
        assert entry.error is None
        assert entry.duration_ms is None
        assert isinstance(entry.started_at, datetime)


class TestOrderServiceSearchLogs:
    @pytest.mark.unit
    def test_finds_pattern(self):
        req = SearchLogsRequest(order_id="1800003902272", pattern="ORDER_STATUS_DENIED")
        resp = OrderService.search_logs(req)
        assert resp.error_found is True
        assert resp.error_code == "ORDER_STATUS_DENIED"
        assert len(resp.matched_samples) > 0
        assert len(resp.logs_full) > 0

    @pytest.mark.unit
    def test_no_match(self):
        req = SearchLogsRequest(order_id="1800003879400", pattern="ORDER_STATUS_DENIED")
        resp = OrderService.search_logs(req)
        assert resp.error_found is False
        assert resp.error_code is None

    @pytest.mark.unit
    def test_nonexistent_order(self):
        req = SearchLogsRequest(order_id="000000", pattern="ORDER_STATUS_DENIED")
        resp = OrderService.search_logs(req)
        assert resp.error_found is False
        assert resp.logs_full == []


class TestOrderServiceGetStatus:
    @pytest.mark.unit
    def test_existing_order(self):
        req = GetOrderStatusRequest(order_id="1800003902272")
        resp = OrderService.get_order_status(req)
        assert resp.status.value == "DENIED"

    @pytest.mark.unit
    def test_missing_order_raises(self):
        req = GetOrderStatusRequest(order_id="000000")
        with pytest.raises(ValueError, match="not found"):
            OrderService.get_order_status(req)


class TestOrderServiceCheckEissd:
    @pytest.mark.unit
    def test_existing_order(self):
        req = CheckEissdStatusRequest(order_id="1800003902272")
        resp = OrderService.check_eissd_status(req)
        assert resp.status.value == "IN_PROGRESS"

    @pytest.mark.unit
    def test_missing_raises(self):
        req = CheckEissdStatusRequest(order_id="000000")
        with pytest.raises(ValueError, match="not found"):
            OrderService.check_eissd_status(req)


class TestOrderServiceUpdateStatus:
    @pytest.mark.unit
    def test_update_existing(self):
        from services.mcp_server.models import OrderStatus as MOrderStatus

        req = UpdateOrderStatusRequest(order_id="1800003902272", new_status=MOrderStatus.DONE)
        resp = OrderService.update_order_status(req)
        assert resp.updated is True
        assert resp.old_status.value == "DENIED"
        assert resp.new_status.value == "DONE"
        assert storage.ORDERS_DB["1800003902272"]["status"] == "DONE"

    @pytest.mark.unit
    def test_create_new(self):
        from services.mcp_server.models import OrderStatus as MOrderStatus

        req = UpdateOrderStatusRequest(order_id="NEW_ORDER", new_status=MOrderStatus.CREATED)
        resp = OrderService.update_order_status(req)
        assert resp.updated is True
        assert "NEW_ORDER" in storage.ORDERS_DB


class TestOtrsServiceQueue:
    @pytest.mark.unit
    def test_resolve_queue(self):
        req = ResolveMrfQueueRequest(region="MSK")
        resp = OtrsService.resolve_mrf_queue(req)
        assert "MSK" in resp.queue

    @pytest.mark.unit
    def test_default_region(self):
        req = ResolveMrfQueueRequest()
        resp = OtrsService.resolve_mrf_queue(req)
        assert "COMMON" in resp.queue


class TestOtrsServiceComments:
    @pytest.mark.unit
    def test_add_and_list(self):
        add_req = AddOtrsCommentRequest(ticket_id="TKT-001", text="Hello")
        resp = OtrsService.add_comment(add_req)
        assert resp.ok is True

        list_req = ListOtrsCommentsRequest(ticket_id="TKT-001")
        listed = OtrsService.list_comments(list_req)
        assert len(listed.comments) >= 1
        assert listed.comments[-1]["text"] == "Hello"

    @pytest.mark.unit
    def test_list_empty(self):
        list_req = ListOtrsCommentsRequest(ticket_id="NONEXISTENT")
        listed = OtrsService.list_comments(list_req)
        assert listed.comments == []


class TestOtrsServiceTicket:
    @pytest.mark.unit
    def test_get_default_ticket(self):
        req = GetOtrsTicketRequest(ticket_id="TKT-999")
        resp = OtrsService.get_ticket(req)
        assert resp.ticket["ticket_id"] == "TKT-999"
        assert resp.ticket["status"] == "NEW"

    @pytest.mark.unit
    def test_update_and_get(self):
        from services.mcp_server.models import OtrsStatus

        update = UpdateOtrsTicketRequest(ticket_id="TKT-001", queue="TestQueue", status=OtrsStatus.OPEN)
        resp = OtrsService.update_ticket(update)
        assert resp.ok is True

        get_resp = OtrsService.get_ticket(GetOtrsTicketRequest(ticket_id="TKT-001"))
        assert get_resp.ticket["queue"] == "TestQueue"
        assert get_resp.ticket["status"] == "OPEN"


class TestModelValidation:
    @pytest.mark.unit
    def test_search_logs_request_bounds(self):
        with pytest.raises(Exception):
            SearchLogsRequest(order_id="X", pattern="Y", window_days=0)

    @pytest.mark.unit
    def test_add_comment_min_length(self):
        with pytest.raises(Exception):
            AddOtrsCommentRequest(ticket_id="X", text="")

    @pytest.mark.unit
    def test_region_enum(self):
        assert Region.MSK.value == "MSK"
        assert Region.COMMON.value == "COMMON"
