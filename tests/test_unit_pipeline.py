"""Юнит-тесты вспомогательных функций pipeline."""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from common.models import ActionLogEntry, Ticket
from pipeline.pipeline import (
    _as_error_dict,
    _ensure_budget,
    _unwrap_mcp_dict,
    build_final_comment,
)


@pytest.fixture
def ticket():
    return Ticket(
        id="TKT-001",
        order_id="ORD-123",
        subject="Test",
        annotation="ann",
        description="desc",
        region="MSK",
        queue="TestQueue",
        created_at=datetime(2025, 1, 1),
    )


class TestUnwrapMcpDict:
    @pytest.mark.unit
    def test_dict_passthrough(self):
        val, code, fatal = _unwrap_mcp_dict("tool", {"key": "value"})
        assert val == {"key": "value"}
        assert code is None
        assert fatal is False

    @pytest.mark.unit
    def test_list_single_dict(self):
        val, code, fatal = _unwrap_mcp_dict("tool", [{"key": "v"}])
        assert val == {"key": "v"}
        assert code is not None
        assert "list_to_dict" in code
        assert fatal is False

    @pytest.mark.unit
    def test_list_multi_dicts(self):
        val, code, fatal = _unwrap_mcp_dict("tool", [{"a": 1}, {"b": 2}])
        assert val == {"a": 1}
        assert "list_multi_dicts" in code
        assert fatal is False

    @pytest.mark.unit
    def test_list_no_dicts(self):
        val, code, fatal = _unwrap_mcp_dict("tool", ["str1", "str2"])
        assert fatal is True
        assert "list_no_dict" in code

    @pytest.mark.unit
    def test_unexpected_type(self):
        val, code, fatal = _unwrap_mcp_dict("tool", 42)
        assert fatal is True
        assert "bad_type" in code


class TestAsErrorDict:
    @pytest.mark.unit
    def test_structure(self):
        result = _as_error_dict("my_tool", [1, 2], "diag.code")
        assert result["error"] == "UNEXPECTED_MCP_RESPONSE"
        assert result["tool"] == "my_tool"
        assert result["diag"] == "diag.code"
        assert result["raw_type"] == "list"


class TestEnsureBudget:
    @pytest.mark.unit
    def test_within_budget(self):
        _ensure_budget(time.monotonic() + 100)

    @pytest.mark.unit
    def test_exceeded(self):
        with pytest.raises(TimeoutError):
            _ensure_budget(time.monotonic() - 1)


class TestBuildFinalComment:
    @pytest.mark.unit
    def test_basic_structure(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={
                "logs": {
                    "error_found": True,
                    "error_code": "ORDER_STATUS_DENIED",
                    "logs_full": ["line1"],
                    "matched_samples": ["line1"],
                },
                "_diag": [],
            },
            rag={"required_actions": [{"tool": "a"}, {"tool": "b"}]},
            actions=[
                ActionLogEntry(tool="t1", params={}, ok=True),
                ActionLogEntry(tool="t2", params={}, ok=True),
            ],
            verify={
                "sulz_db": {"status": "DONE"},
                "eissd": {"status": "IN_PROGRESS"},
                "_diag": [],
            },
        )
        assert "RTK_AGENT_FINAL v1" in comment
        assert "ticket_id=TKT-001" in comment
        assert "order_id=ORD-123" in comment
        assert "region=MSK" in comment
        assert "precheck.error_found=true" in comment
        assert "rag.required_actions_count=2" in comment
        assert "actions.count=2" in comment
        assert "actions.ok=true" in comment
        assert "verify.sulz_db.status=DONE" in comment
        assert "verify.eissd.status=IN_PROGRESS" in comment
        assert "next_step=IN_WORK_WAIT_CONFIRMATION" in comment

    @pytest.mark.unit
    def test_no_error_next_step(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": False}, "_diag": []},
            rag=None,
            actions=[],
            verify={"sulz_db": None, "eissd": None, "_diag": []},
        )
        assert "next_step=NO_ERROR_IN_LOGS" in comment

    @pytest.mark.unit
    def test_failed_actions_escalate(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={
                "logs": {"error_found": True, "error_code": "X"},
                "_diag": [],
            },
            rag=None,
            actions=[ActionLogEntry(tool="t1", params={}, ok=False, error="fail")],
            verify={"_diag": []},
        )
        assert "next_step=ESCALATE_L2" in comment
        assert "actions.ok=false" in comment

    @pytest.mark.unit
    def test_diag_codes_included(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": False}, "_diag": ["diag.a"]},
            rag=None,
            actions=[],
            verify={"_diag": ["diag.b"]},
        )
        assert "diag.count=2" in comment
        assert "diag.0=diag.a" in comment
        assert "diag.1=diag.b" in comment

    @pytest.mark.unit
    def test_empty_precheck(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={},
            rag=None,
            actions=[],
            verify={"_diag": []},
        )
        assert "precheck.error_found=false" in comment
        assert "next_step=NO_ERROR_IN_LOGS" in comment

    @pytest.mark.unit
    def test_real_rag_block_emitted(self, ticket):
        """Реальный RAG через rag_adapter — rag.relevance / rag.answer.* / rag.sources_count."""
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True}, "_diag": []},
            rag={
                "required_actions": [],
                "conditions": {"rag_relevance": "direct", "matched_current_order": True},
                "parameters": {
                    "rag_relevance": "direct",
                    "rag_full_length": 1234,
                    "rag_filtered_length": 350,
                    "rag_order_ids_found": ["ORD-123", "OTHER-1"],
                    "rag_matched_current_order": True,
                    "cached": False,
                },
                "answer_text": "1. Перевести заявку ORD-123 в отказ.\n2. Высвободить СН.",
                "sources": [{"url": "https://confluence/x", "page_title": "P"}],
            },
            actions=[ActionLogEntry(tool="check_eissd_status", params={}, ok=True)],
            verify={"sulz_db": {"status": "DONE"}, "eissd": {"status": "DONE"}, "_diag": []},
        )
        assert "rag.relevance=direct" in comment
        assert "rag.full_length=1234" in comment
        assert "rag.filtered_length=350" in comment
        assert "rag.matched_current_order=true" in comment
        assert "rag.order_ids_found.count=2" in comment
        assert "rag.order_ids_found=ORD-123,OTHER-1" in comment
        assert "rag.sources_count=1" in comment
        assert "rag.answer.0=1. Перевести заявку ORD-123 в отказ." in comment
        assert "rag.answer.1=2. Высвободить СН." in comment

    @pytest.mark.unit
    def test_real_rag_block_absent_for_mock(self, ticket):
        """Мок-RAG — без answer_text/parameters блок rag.* новой формы не эмитится."""
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True}, "_diag": []},
            rag={"required_actions": [{"tool": "check_eissd_status"}]},
            actions=[ActionLogEntry(tool="check_eissd_status", params={}, ok=True)],
            verify={"_diag": []},
        )
        # Legacy-блок сохранён.
        assert "rag.required_actions_count=1" in comment
        assert "rag.action.count=1" in comment
        # Новые поля real-RAG отсутствуют — их нечего показывать.
        assert "rag.relevance=" not in comment
        assert "rag.answer.0" not in comment


class TestVerifyFinalStatusLogsRecheck:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_logs_recheck_populated_on_success(self, ticket):
        from unittest.mock import AsyncMock
        from pipeline.pipeline import verify_final_status

        mcp = AsyncMock()

        async def call_tool(name, args):
            if name == "get_order_status":
                return {"status": "DONE", "raw": {}}
            if name == "check_eissd_status":
                return {"status": "DONE", "raw": {}}
            if name == "search_logs":
                return {"error_found": False, "logs_full": []}
            raise ValueError(f"unexpected tool {name}")

        mcp.call_tool.side_effect = call_tool

        results, _logs = await verify_final_status(
            ticket, mcp, deadline=time.monotonic() + 30
        )
        assert "logs_recheck" in results
        lr = results["logs_recheck"]
        assert lr["error_still_present"] is False
        assert lr["logs_full_count"] == 0
        assert lr["window_days"] == 1
        assert lr["pattern"] == "ORDER_STATUS_DENIED"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_logs_recheck_error_still_present(self, ticket):
        from unittest.mock import AsyncMock
        from pipeline.pipeline import verify_final_status

        mcp = AsyncMock()

        async def call_tool(name, args):
            if name == "get_order_status":
                return {"status": "DONE", "raw": {}}
            if name == "check_eissd_status":
                return {"status": "DONE", "raw": {}}
            if name == "search_logs":
                return {"error_found": True, "error_code": "ORDER_STATUS_DENIED", "logs_full": ["l1", "l2"]}
            raise ValueError(f"unexpected tool {name}")

        mcp.call_tool.side_effect = call_tool

        results, _logs = await verify_final_status(ticket, mcp, deadline=time.monotonic() + 30)
        assert results["logs_recheck"]["error_still_present"] is True
        assert results["logs_recheck"]["logs_full_count"] == 2

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_logs_recheck_mcp_exception(self, ticket):
        from unittest.mock import AsyncMock
        from pipeline.pipeline import verify_final_status

        mcp = AsyncMock()

        async def call_tool(name, args):
            if name == "get_order_status":
                return {"status": "DONE", "raw": {}}
            if name == "check_eissd_status":
                return {"status": "DONE", "raw": {}}
            if name == "search_logs":
                raise RuntimeError("mcp down")
            raise ValueError(f"unexpected tool {name}")

        mcp.call_tool.side_effect = call_tool

        results, _logs = await verify_final_status(ticket, mcp, deadline=time.monotonic() + 30)
        assert results["logs_recheck"]["error_still_present"] is None


class TestEvaluateLlmOutcome:
    @pytest.mark.unit
    def test_no_escalation_when_error_and_actions_taken(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": True}},
            "llm_metrics": {
                "steps_used": 5,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is False
        assert reasons == []

    @pytest.mark.unit
    def test_no_action_taken_triggers(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": True}},
            "llm_metrics": {
                "steps_used": 1,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is True
        assert "llm_no_action_taken" in reasons

    @pytest.mark.unit
    def test_loop_exceeded_triggers(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": False}},
            "llm_metrics": {
                "steps_used": 12,
                "write_calls_total": 1,
                "loop_exceeded": True,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is True
        assert "llm_loop_exceeded" in reasons

    @pytest.mark.unit
    def test_tool_errors_repeated_triggers(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": True}},
            "llm_metrics": {
                "steps_used": 3,
                "write_calls_total": 1,
                "loop_exceeded": False,
                "error_count": 3,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is True
        assert "llm_tool_errors_repeated" in reasons

    @pytest.mark.unit
    def test_no_error_found_and_zero_actions_is_fine(self):
        from pipeline.pipeline import _evaluate_llm_outcome
        context = {
            "precheck": {"logs": {"error_found": False}},
            "llm_metrics": {
                "steps_used": 0,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            },
        }
        escalate, reasons = _evaluate_llm_outcome([], context)
        assert escalate is False
        assert reasons == []


class TestBuildFinalCommentExtended:
    @pytest.mark.unit
    def test_llm_metrics_fields_present(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True, "error_code": "X"}, "_diag": []},
            rag={"required_actions": []},
            actions=[ActionLogEntry(tool="t1", params={}, ok=True)],
            verify={"_diag": [], "logs_recheck": {
                "pattern": "ORDER_STATUS_DENIED",
                "window_days": 1,
                "error_still_present": False,
                "logs_full_count": 0,
            }},
            llm_metrics={
                "steps_used": 5,
                "rag_followed": 1,
                "rag_deviated": 0,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            },
            escalate_reasons=[],
        )
        assert "llm.steps_used=5" in comment
        assert "llm.rag_followed=1" in comment
        assert "llm.rag_deviated=0" in comment
        assert "llm.write_calls_total=2" in comment
        assert "llm.loop_exceeded=false" in comment
        assert "llm.error_count=0" in comment
        assert "verify.logs_recheck.window_days=1" in comment
        assert "verify.logs_recheck.error_still_present=false" in comment
        assert "verify.logs_recheck.logs_full_count=0" in comment
        assert "escalate.triggered=false" in comment

    @pytest.mark.unit
    def test_escalate_reason_appended_from_verify(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True}, "_diag": []},
            rag=None,
            actions=[ActionLogEntry(tool="t1", params={}, ok=True)],
            verify={"_diag": [], "logs_recheck": {
                "pattern": "ORDER_STATUS_DENIED",
                "window_days": 1,
                "error_still_present": True,
                "logs_full_count": 3,
            }},
            llm_metrics={
                "steps_used": 5,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 2,
                "loop_exceeded": False,
                "error_count": 0,
            },
            escalate_reasons=[],
        )
        assert "escalate.triggered=true" in comment
        assert "escalate.reason.0=error_persists_after_execution" in comment
        assert "next_step=ESCALATE_L2" in comment

    @pytest.mark.unit
    def test_escalate_pre_verify_reason(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": True}, "_diag": []},
            rag=None,
            actions=[],
            verify={"_diag": [], "logs_recheck": {
                "pattern": "ORDER_STATUS_DENIED",
                "window_days": 1,
                "error_still_present": False,
                "logs_full_count": 0,
            }},
            llm_metrics={
                "steps_used": 1,
                "rag_followed": 0,
                "rag_deviated": 0,
                "write_calls_total": 0,
                "loop_exceeded": False,
                "error_count": 0,
            },
            escalate_reasons=["llm_no_action_taken"],
        )
        assert "escalate.triggered=true" in comment
        assert "escalate.reason.0=llm_no_action_taken" in comment
        assert "next_step=ESCALATE_L2" in comment

    @pytest.mark.unit
    def test_build_final_comment_backward_compat_optional_args(self, ticket):
        comment = build_final_comment(
            ticket,
            precheck={"logs": {"error_found": False}, "_diag": []},
            rag=None,
            actions=[],
            verify={"_diag": []},
        )
        assert "next_step=NO_ERROR_IN_LOGS" in comment
        assert "llm.steps_used=" in comment
        assert "escalate.triggered=false" in comment
