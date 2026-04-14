"""Юнит-тесты для helper-функций llm_service.

Покрывают две новые функции, добавленные для интеграции с реальным RAG:

- ``build_precheck_fallback_plan`` — детерминированный план по precheck.
- ``_build_rag_context_block`` — сборка блока с текстом RAG в system prompt.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from common.models import Ticket
from services.llm_service import (
    _build_rag_context_block,
    _precheck_error_found,
    build_precheck_fallback_plan,
)


def _make_ticket(order_id: str = "1800003858739") -> Ticket:
    return Ticket(
        id="T-1",
        order_id=order_id,
        subject="Заявка уже отправлена в СУЛЗ",
        annotation="ann",
        description="desc",
        region="Юг",
        queue=None,
        created_at=datetime(2026, 4, 12, 10, 0, 0),
    )


# ---------------------------------------------------------------------------
# build_precheck_fallback_plan
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_precheck_error_found_true_adds_check_edit_order() -> None:
    ticket = _make_ticket()
    ctx: dict[str, Any] = {"precheck": {"logs": {"error_found": True}}}
    plan = build_precheck_fallback_plan(ticket, ctx)
    tools = [step["tool"] for step in plan]
    assert tools == [
        "check_eissd_status",
        "get_order_status",
        "check_edit_order_request",
    ]
    for step in plan:
        assert step["arguments"]["order_id"] == ticket.order_id


@pytest.mark.unit
def test_precheck_error_found_false_skips_write_probes() -> None:
    ticket = _make_ticket()
    ctx: dict[str, Any] = {"precheck": {"logs": {"error_found": False}}}
    plan = build_precheck_fallback_plan(ticket, ctx)
    tools = [step["tool"] for step in plan]
    assert tools == ["check_eissd_status", "get_order_status"]
    # check_edit_order_request — write-инструмент, без подтверждённой ошибки не дёргаем.
    assert "check_edit_order_request" not in tools


@pytest.mark.unit
def test_precheck_missing_context_defaults_to_read_only() -> None:
    ticket = _make_ticket()
    plan = build_precheck_fallback_plan(ticket, None)
    assert [step["tool"] for step in plan] == [
        "check_eissd_status",
        "get_order_status",
    ]


@pytest.mark.unit
def test_precheck_invalid_logs_type_defaults_to_read_only() -> None:
    ticket = _make_ticket()
    ctx: dict[str, Any] = {"precheck": {"logs": "not-a-dict"}}
    plan = build_precheck_fallback_plan(ticket, ctx)
    assert [step["tool"] for step in plan] == [
        "check_eissd_status",
        "get_order_status",
    ]


@pytest.mark.unit
def test_precheck_error_found_helper_handles_edge_cases() -> None:
    assert _precheck_error_found(None) is False
    assert _precheck_error_found({}) is False
    assert _precheck_error_found({"precheck": None}) is False
    assert _precheck_error_found({"precheck": {"logs": None}}) is False
    assert _precheck_error_found({"precheck": {"logs": {}}}) is False
    assert _precheck_error_found({"precheck": {"logs": {"error_found": True}}}) is True
    assert _precheck_error_found({"precheck": {"logs": {"error_found": False}}}) is False


# ---------------------------------------------------------------------------
# _build_rag_context_block
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rag_block_empty_when_no_context() -> None:
    assert _build_rag_context_block(None) == ""
    assert _build_rag_context_block({}) == ""


@pytest.mark.unit
def test_rag_block_empty_when_rag_missing_or_wrong_type() -> None:
    assert _build_rag_context_block({"rag": None}) == ""
    assert _build_rag_context_block({"rag": "string"}) == ""


@pytest.mark.unit
def test_rag_block_empty_when_answer_text_missing() -> None:
    # Типичный случай documentation/empty — rag_adapter вернул answer_text=None.
    ctx = {
        "rag": {
            "answer_text": None,
            "parameters": {"rag_relevance": "documentation"},
        }
    }
    assert _build_rag_context_block(ctx) == ""


@pytest.mark.unit
def test_rag_block_empty_when_answer_text_whitespace() -> None:
    ctx = {
        "rag": {
            "answer_text": "   \n\t  ",
            "parameters": {"rag_relevance": "direct"},
        }
    }
    assert _build_rag_context_block(ctx) == ""


@pytest.mark.unit
def test_rag_block_direct_includes_answer_and_relevance() -> None:
    ctx = {
        "rag": {
            "answer_text": "1. Перевести заявку 1800003879409 в отказ в ЕИССД.",
            "parameters": {"rag_relevance": "direct"},
        }
    }
    block = _build_rag_context_block(ctx)
    assert "relevance=direct" in block
    assert "1800003879409" in block
    assert "похожий кейс" in block  # подсказка для direct


@pytest.mark.unit
def test_rag_block_batch_historical_has_foreign_order_warning() -> None:
    """Критично: LLM должна ЯВНО увидеть предупреждение про чужие order_id."""
    ctx = {
        "rag": {
            "answer_text": "1. Для <other_order> перевести в отказ.\n2. Для <other_order> проверить СН.",
            "parameters": {"rag_relevance": "batch_historical"},
        }
    }
    block = _build_rag_context_block(ctx)
    assert "relevance=batch_historical" in block
    assert "ВНИМАНИЕ" in block
    assert "<other_order>" in block
    # Должно быть упоминание запрета подставлять чужие id.
    assert "НЕ подставляй" in block or "НИ В КОЕМ СЛУЧАЕ не" in block


@pytest.mark.unit
def test_rag_block_general_guidance_has_generic_hint() -> None:
    ctx = {
        "rag": {
            "answer_text": "1. Проверить статус в ЕИССД.\n2. Высвободить СН на складе.",
            "parameters": {"rag_relevance": "general_guidance"},
        }
    }
    block = _build_rag_context_block(ctx)
    assert "relevance=general_guidance" in block
    assert "общие рекомендации" in block


@pytest.mark.unit
def test_rag_block_fallback_relevance_from_conditions() -> None:
    """relevance может прийти через conditions, а не parameters."""
    ctx = {
        "rag": {
            "answer_text": "1. Перевести заявку.",
            "conditions": {"rag_relevance": "direct"},
        }
    }
    block = _build_rag_context_block(ctx)
    assert "relevance=direct" in block


@pytest.mark.unit
def test_rag_block_unknown_relevance_uses_generic_hint() -> None:
    ctx = {
        "rag": {
            "answer_text": "Какой-то текст от RAG.",
            "parameters": {"rag_relevance": "something_new"},
        }
    }
    block = _build_rag_context_block(ctx)
    assert "relevance=something_new" in block
    assert "справочный материал" in block
