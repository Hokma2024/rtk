"""E2E / smoke-тесты.

Сквозные сценарии через FastAPI TestClient. Не требуют внешних сервисов
(LLM, Ollama) — используется детерминированный fallback-режим.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_api.main import app
from common.models import ActionLogEntry


@pytest.fixture
def client():
    mock_mcp = AsyncMock()
    app.state.mcp = mock_mcp
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestHealthEndpoint:
    @pytest.mark.e2e
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestMetricsEndpoint:
    @pytest.mark.e2e
    def test_metrics_returns_prometheus(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "agent_requests_total" in resp.text or "text/plain" in resp.headers.get("content-type", "")


class TestTicketIntakeE2E:
    @pytest.mark.e2e
    def test_successful_intake(self, client):
        mock_actions = [ActionLogEntry(tool="check_eissd_status", params={"order_id": "O1"}, ok=True)]
        mock_verify = (
            {"sulz_db": {"status": "DONE"}, "eissd": {"status": "DONE"}, "_diag": []},
            [],
        )
        mock_comment = "RTK_AGENT_FINAL v1\nticket_id=T1\nnext_step=NO_ERROR_IN_LOGS\n"

        with (
            patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre,
            patch("agent_api.main.call_rag", new_callable=AsyncMock) as m_rag,
            patch("agent_api.main.plan_and_execute", new_callable=AsyncMock) as m_plan,
            patch("agent_api.main.verify_final_status", new_callable=AsyncMock) as m_verify,
            patch("agent_api.main.build_final_comment") as m_comment,
            patch("agent_api.main.finalize", new_callable=AsyncMock) as m_finalize,
        ):
            m_pre.return_value = {"precheck": {"logs": {"error_found": False}}}
            m_rag.return_value = {"rag": None}
            m_plan.return_value = mock_actions
            m_verify.return_value = mock_verify
            m_comment.return_value = mock_comment
            m_finalize.return_value = []

            resp = client.post(
                "/tickets/intake",
                json={
                    "id": "T1",
                    "order_id": "O1",
                    "description": "Test order",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["ticket_id"] == "T1"
            assert "RTK_AGENT_FINAL" in data["final_comment"]

    @pytest.mark.e2e
    def test_timeout_returns_504(self, client):
        with patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre:
            m_pre.side_effect = TimeoutError("Budget exceeded")

            resp = client.post(
                "/tickets/intake",
                json={
                    "id": "T1",
                    "order_id": "O1",
                    "description": "desc",
                },
            )
            assert resp.status_code == 504

    @pytest.mark.e2e
    def test_internal_error_returns_500(self, client):
        with patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre:
            m_pre.side_effect = RuntimeError("Unexpected")

            resp = client.post(
                "/tickets/intake",
                json={
                    "id": "T1",
                    "order_id": "O1",
                    "description": "desc",
                },
            )
            assert resp.status_code == 500

    @pytest.mark.e2e
    def test_happy_path_with_rag(self, client):
        mock_actions = [
            ActionLogEntry(tool="check_edit_order_request", params={"order_id": "O1"}, ok=True),
            ActionLogEntry(tool="update_order_status", params={"order_id": "O1"}, ok=True),
        ]

        async def fake_plan(ticket, ctx, mcp, deadline):
            ctx["llm_metrics"] = {
                "steps_used": 3,
                "rag_followed": 2,
                "rag_deviated": 0,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            }
            return mock_actions

        mock_verify = (
            {
                "sulz_db": {"status": "DONE"},
                "eissd": {"status": "DONE"},
                "_diag": [],
                "logs_recheck": {
                    "pattern": "ORDER_STATUS_DENIED",
                    "window_days": 1,
                    "error_still_present": False,
                    "logs_full_count": 0,
                },
            },
            [],
        )

        with (
            patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre,
            patch("agent_api.main.call_rag", new_callable=AsyncMock) as m_rag,
            patch("agent_api.main.plan_and_execute", side_effect=fake_plan),
            patch("agent_api.main.verify_final_status", new_callable=AsyncMock) as m_verify,
            patch("agent_api.main.finalize", new_callable=AsyncMock) as m_finalize,
        ):
            m_pre.return_value = {
                "precheck": {"logs": {"error_found": True, "error_code": "ORDER_STATUS_DENIED"}, "_diag": []}
            }
            m_rag.return_value = {"rag": {"required_actions": [
                {"tool": "check_edit_order_request"},
                {"tool": "update_order_status"},
            ]}}
            m_verify.return_value = mock_verify
            m_finalize.return_value = []

            resp = client.post(
                "/tickets/intake",
                json={"id": "T-HAPPY", "order_id": "O1", "description": "desc"},
            )
            assert resp.status_code == 200
            body = resp.json()["final_comment"]
            assert "llm.rag_followed=2" in body
            assert "escalate.triggered=false" in body
            assert "next_step=IN_WORK_WAIT_CONFIRMATION" in body

    @pytest.mark.e2e
    def test_zero_action_escalation(self, client):
        async def fake_plan(ticket, ctx, mcp, deadline):
            ctx["llm_metrics"] = {
                "steps_used": 1,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            }
            return []

        mock_verify = (
            {
                "sulz_db": {"status": "DENIED"},
                "eissd": {"status": "IN_PROGRESS"},
                "_diag": [],
                "logs_recheck": {
                    "pattern": "ORDER_STATUS_DENIED",
                    "window_days": 1,
                    "error_still_present": True,
                    "logs_full_count": 1,
                },
            },
            [],
        )

        with (
            patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre,
            patch("agent_api.main.call_rag", new_callable=AsyncMock) as m_rag,
            patch("agent_api.main.plan_and_execute", side_effect=fake_plan),
            patch("agent_api.main.verify_final_status", new_callable=AsyncMock) as m_verify,
            patch("agent_api.main.finalize", new_callable=AsyncMock) as m_finalize,
        ):
            m_pre.return_value = {
                "precheck": {"logs": {"error_found": True, "error_code": "ORDER_STATUS_DENIED"}, "_diag": []}
            }
            m_rag.return_value = {"rag": None}
            m_verify.return_value = mock_verify
            m_finalize.return_value = []

            resp = client.post(
                "/tickets/intake",
                json={"id": "T-ZERO", "order_id": "O2", "description": "desc"},
            )
            assert resp.status_code == 200
            body = resp.json()["final_comment"]
            assert "llm.write_calls_total=0" in body
            assert "escalate.triggered=true" in body
            assert "escalate.reason.0=llm_no_action_taken" in body
            assert "next_step=ESCALATE_L2" in body

    @pytest.mark.e2e
    def test_mrf_cycle_via_stub_llm(self, client):
        mock_actions = [
            ActionLogEntry(
                tool="resolve_mrf_queue", params={"region": "MSK"}, ok=True,
                result={"queue": "ОЦО.МРФ.Эксплуатация СУЛЗ.MSK"},
            ),
            ActionLogEntry(
                tool="mrf_process_ticket",
                params={"ticket_id": "T-MRF", "order_id": "O3", "region": "MSK"},
                ok=True,
                result={
                    "mrf_verdict": "OK",
                    "comment_added": True,
                    "queue": "ОЦО.МРФ.Эксплуатация СУЛЗ.MSK",
                    "details": {},
                },
            ),
            ActionLogEntry(
                tool="list_otrs_comments", params={"ticket_id": "T-MRF"}, ok=True,
                result={"comments": [{"ticket_id": "T-MRF", "text": "МРФ: OK", "source": "mrf_mock"}]},
            ),
        ]

        async def fake_plan(ticket, ctx, mcp, deadline):
            ctx["llm_metrics"] = {
                "steps_used": 3,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            }
            return mock_actions

        mock_verify = (
            {
                "sulz_db": {"status": "DONE"},
                "eissd": {"status": "DONE"},
                "_diag": [],
                "logs_recheck": {
                    "pattern": "ORDER_STATUS_DENIED",
                    "window_days": 1,
                    "error_still_present": False,
                    "logs_full_count": 0,
                },
            },
            [],
        )

        with (
            patch("agent_api.main.precheck_logs", new_callable=AsyncMock) as m_pre,
            patch("agent_api.main.call_rag", new_callable=AsyncMock) as m_rag,
            patch("agent_api.main.plan_and_execute", side_effect=fake_plan),
            patch("agent_api.main.verify_final_status", new_callable=AsyncMock) as m_verify,
            patch("agent_api.main.finalize", new_callable=AsyncMock) as m_finalize,
        ):
            m_pre.return_value = {
                "precheck": {"logs": {"error_found": True, "error_code": "ORDER_STATUS_DENIED"}, "_diag": []}
            }
            m_rag.return_value = {"rag": None}
            m_verify.return_value = mock_verify
            m_finalize.return_value = []

            resp = client.post(
                "/tickets/intake",
                json={"id": "T-MRF", "order_id": "O3", "description": "desc", "region": "MSK"},
            )
            assert resp.status_code == 200
            body = resp.json()["final_comment"]
            assert "llm.write_calls_total=2" in body
            assert "escalate.triggered=false" in body
            assert "next_step=IN_WORK_WAIT_CONFIRMATION" in body


class TestInputValidation:
    @pytest.mark.e2e
    def test_missing_required_field(self, client):
        resp = client.post(
            "/tickets/intake",
            json={
                "order_id": "O1",
                "description": "desc",
            },
        )
        assert resp.status_code == 422

    @pytest.mark.e2e
    def test_empty_body(self, client):
        resp = client.post("/tickets/intake", json={})
        assert resp.status_code == 422
