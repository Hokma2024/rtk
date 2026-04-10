"""Unit-тесты мока mrf_process_ticket."""
from __future__ import annotations

import pytest

from services.mcp_server import storage
from services.mcp_server.models import ListOtrsCommentsRequest, MrfProcessTicketRequest
from services.mcp_server.services import OtrsService


class TestMrfProcessTicket:
    @pytest.mark.unit
    def test_deterministic_same_order_same_verdict(self):
        req = MrfProcessTicketRequest(ticket_id="T1", order_id="1800003902272", region="MSK")
        r1 = OtrsService.mrf_process_ticket(req)
        storage.OTRS_COMMENTS.clear()
        r2 = OtrsService.mrf_process_ticket(req)
        assert r1.mrf_verdict == r2.mrf_verdict

    @pytest.mark.unit
    def test_comment_added_to_storage(self):
        req = MrfProcessTicketRequest(ticket_id="T-COMMENT", order_id="1800003902272", region="MSK")
        before = len([c for c in storage.OTRS_COMMENTS if c.get("ticket_id") == "T-COMMENT"])
        resp = OtrsService.mrf_process_ticket(req)
        after = [c for c in storage.OTRS_COMMENTS if c.get("ticket_id") == "T-COMMENT"]
        assert resp.comment_added is True
        assert len(after) == before + 1
        assert after[-1].get("source") == "mrf_mock"

    @pytest.mark.unit
    def test_all_verdicts_reachable(self):
        verdicts = set()
        for i in range(200):
            req = MrfProcessTicketRequest(ticket_id=f"T{i}", order_id=f"ORD{i}", region="MSK")
            r = OtrsService.mrf_process_ticket(req)
            verdicts.add(r.mrf_verdict)
            storage.OTRS_COMMENTS.clear()
        assert verdicts == {"OK", "NEEDS_MANUAL", "EDIT_ORDER_PENDING", "ORDER_NOT_FOUND_IN_EISSD"}

    @pytest.mark.unit
    def test_queue_reflects_region(self):
        req = MrfProcessTicketRequest(ticket_id="T1", order_id="1800003902272", region="SPB")
        resp = OtrsService.mrf_process_ticket(req)
        assert "SPB" in resp.queue

    @pytest.mark.unit
    def test_list_comments_includes_mrf_comment(self):
        req = MrfProcessTicketRequest(ticket_id="T-LIST", order_id="1800003902272", region="MSK")
        OtrsService.mrf_process_ticket(req)
        resp = OtrsService.list_comments(ListOtrsCommentsRequest(ticket_id="T-LIST"))
        assert any(c.get("source") == "mrf_mock" for c in resp.comments)
