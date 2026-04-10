"""Контрактные тесты HTTP API.

Проверяют контракты без запущенного LLM-бэкенда — все внешние зависимости
либо замоканы, либо используют детерминированный fallback.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_api.main import TicketIn, TicketOut
from pipeline.rag_models import RagRequest, RagResponse


class TestTicketInContract:
    @pytest.mark.contract
    def test_valid_minimal(self):
        t = TicketIn(id="T1", order_id="O1", description="desc")
        assert t.id == "T1"
        assert t.subject == ""
        assert t.region == "COMMON"
        assert t.queue is None
        assert t.metadata is None

    @pytest.mark.contract
    def test_valid_full(self):
        t = TicketIn(
            id="T2",
            order_id="O2",
            subject="subj",
            annotation="ann",
            description="full",
            region="MSK",
            queue="Q1",
            metadata={"key": "val"},
        )
        assert t.region == "MSK"
        assert t.metadata["key"] == "val"

    @pytest.mark.contract
    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            TicketIn(order_id="O1", description="desc")  # отсутствует id

    @pytest.mark.contract
    def test_missing_description(self):
        with pytest.raises(ValidationError):
            TicketIn(id="T1", order_id="O1")  # отсутствует description

    @pytest.mark.contract
    def test_serialisation_round_trip(self):
        t = TicketIn(id="T1", order_id="O1", description="desc")
        data = t.model_dump()
        t2 = TicketIn(**data)
        assert t == t2


class TestTicketOutContract:
    @pytest.mark.contract
    def test_valid_minimal(self):
        out = TicketOut(ticket_id="T1", final_comment="comment", summary="sum")
        assert out.actions is None

    @pytest.mark.contract
    def test_with_actions(self):
        out = TicketOut(
            ticket_id="T1",
            final_comment="comment",
            summary="sum",
            actions=[{"tool": "t1", "ok": True}],
        )
        assert len(out.actions) == 1

    @pytest.mark.contract
    def test_serialisation(self):
        out = TicketOut(ticket_id="T1", final_comment="c", summary="s")
        j = out.model_dump_json()
        assert "ticket_id" in j


class TestRagContracts:
    @pytest.mark.contract
    def test_rag_request_defaults(self):
        req = RagRequest(
            ticket_id="T1",
            order_id="O1",
            subject="s",
            annotation="a",
            description="d",
        )
        assert req.precheck == {}

    @pytest.mark.contract
    def test_rag_response_defaults(self):
        resp = RagResponse()
        assert resp.required_actions == []
        assert resp.conditions == {}
        assert resp.parameters == {}

    @pytest.mark.contract
    def test_rag_response_with_actions(self):
        resp = RagResponse(
            required_actions=[{"tool": "check_eissd_status", "arguments": {"order_id": "O1"}}],
            conditions={"error_found": True},
            parameters={"ticket_id": "T1"},
        )
        assert len(resp.required_actions) == 1
        assert resp.conditions["error_found"] is True

    @pytest.mark.contract
    def test_rag_round_trip(self):
        req = RagRequest(
            ticket_id="T1",
            order_id="O1",
            subject="s",
            annotation="a",
            description="d",
            precheck={"logs": {"error_found": True}},
        )
        data = req.model_dump()
        req2 = RagRequest(**data)
        assert req.precheck == req2.precheck


class TestRagMockLogic:
    @pytest.mark.contract
    def test_error_found_returns_full_mrf_plan(self):
        import asyncio

        from services.rag_mock.main import query

        req = RagRequest(
            ticket_id="T1",
            order_id="O1",
            subject="s",
            annotation="a",
            description="d",
            precheck={"logs": {"error_found": True}},
        )
        resp = asyncio.get_event_loop().run_until_complete(query(req))
        tool_names = [a["tool"] for a in resp.required_actions]
        assert tool_names == [
            "get_order_status",
            "check_eissd_status",
            "check_edit_order_request",
            "resolve_mrf_queue",
            "mrf_process_ticket",
            "list_otrs_comments",
        ]

    @pytest.mark.contract
    def test_no_error_returns_1_action(self):
        import asyncio

        from services.rag_mock.main import query

        req = RagRequest(
            ticket_id="T1",
            order_id="O1",
            subject="s",
            annotation="a",
            description="d",
            precheck={"logs": {"error_found": False}},
        )
        resp = asyncio.get_event_loop().run_until_complete(query(req))
        assert len(resp.required_actions) == 1
