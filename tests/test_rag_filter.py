"""Юнит-тесты фильтра rag_adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.rag_adapter.classifier import ORDER_ID_RE
from services.rag_adapter.filter import (
    DEFAULT_MAX_LEN,
    filter_rag_response,
    summarize_order_ids,
)

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "rag_real_responses.json"


def load_fixtures() -> list[dict]:
    with FIXTURES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.unit
@pytest.mark.parametrize("case", load_fixtures(), ids=lambda c: c["id"])
def test_filter_matches_expectations(case: dict) -> None:
    filtered = filter_rag_response(
        case["expected_type"],
        case["raw_answer"],
        case["current_order_id"],
    )
    expect_empty = case.get("expected_filter_empty", False)
    if expect_empty:
        assert filtered == "", f"Case {case['id']}: expected empty filter, got {filtered!r}"
    else:
        assert filtered, f"Case {case['id']}: expected non-empty filter"

    for needle in case.get("expected_filter_contains", []):
        assert needle in filtered, (
            f"Case {case['id']}: expected '{needle}' in filtered text, got {filtered!r}"
        )

    if case.get("expected_no_foreign_order_ids"):
        found = ORDER_ID_RE.findall(filtered)
        foreign = [x for x in found if x != case["current_order_id"]]
        assert not foreign, (
            f"Case {case['id']}: foreign order_ids leaked through filter: {foreign}"
        )


@pytest.mark.unit
def test_filter_documentation_returns_empty_string() -> None:
    text = "п. 3.5.25 описывает параметр X, автор: Савельева. Согласно изменениям от 07.03.2024."
    assert filter_rag_response("documentation", text, "1800003879409") == ""


@pytest.mark.unit
def test_filter_empty_returns_empty_string() -> None:
    assert filter_rag_response("empty", "", "1800003879409") == ""
    assert filter_rag_response("empty", "some text", "1800003879409") == ""


@pytest.mark.unit
def test_filter_direct_keeps_current_order() -> None:
    text = (
        "1. Перевести заявку 1800003879409 в отказ.\n"
        "2. Высвободить серийные номера.\n"
        "3. Другое действие без контекста."
    )
    out = filter_rag_response("direct", text, "1800003879409")
    assert "1800003879409" in out
    assert "Перевести" in out


@pytest.mark.unit
def test_filter_batch_historical_normalizes_foreign_ids() -> None:
    text = (
        "1. Для 1111111111 перевести в отказ в ЕИССД.\n"
        "2. Для 2222222222 проверить СН в СРЕ.\n"
        "3. Для 3333333333 закрыть заявку как дубликат.\n"
        "4. Для 4444444444 высвободить серийники."
    )
    out = filter_rag_response("batch_historical", text, "9999999999")
    ids_in_output = ORDER_ID_RE.findall(out)
    assert all(x == "9999999999" or x == "<other_order>" for x in ids_in_output) or not ids_in_output
    # Проверяем, что плейсхолдер появился
    assert "<other_order>" in out


@pytest.mark.unit
def test_filter_batch_historical_keeps_current_id() -> None:
    text = (
        "1. Для 1800003906136 перевести в отказ в ЕИССД.\n"
        "2. Для 1800003924975 проверить дубликат СН.\n"
        "3. Для 1800003931567 перевести в отказ.\n"
        "4. Для 1800003898802 проверить CREATE_ORDER."
    )
    out = filter_rag_response("batch_historical", text, "1800003906136")
    assert "1800003906136" in out
    # Чужие заменены на плейсхолдер
    foreign = [x for x in ORDER_ID_RE.findall(out) if x != "1800003906136"]
    assert not foreign


@pytest.mark.unit
def test_filter_general_guidance_keeps_action_items() -> None:
    text = (
        "1. Проверить статус заявки в ЕИССД и перевести в отказ при расхождении.\n"
        "2. Высвободить серийные номера на складе в СРЕ.\n"
        "3. Описание процесса без конкретных действий.\n"
    )
    out = filter_rag_response("general_guidance", text, "1800003858739")
    assert "Проверить" in out or "перевести" in out.lower()


@pytest.mark.unit
def test_filter_respects_max_len() -> None:
    long_text = "1. Перевести заявку 1800003879409 в отказ в ЕИССД. " * 200
    out = filter_rag_response("direct", long_text, "1800003879409", max_len=500)
    assert len(out) <= 510  # небольшой люфт на "\n…"


@pytest.mark.unit
def test_summarize_order_ids() -> None:
    text = "1111111111 2222222222 3333333333 1111111111"
    ids, matched = summarize_order_ids(text, "2222222222")
    assert ids == ["1111111111", "2222222222", "3333333333"]
    assert matched is True

    ids2, matched2 = summarize_order_ids(text, "9999999999")
    assert matched2 is False


@pytest.mark.unit
def test_default_max_len_is_reasonable() -> None:
    # Проверка, что DEFAULT_MAX_LEN не случайно выставлен в 0 или 999999
    assert 500 <= DEFAULT_MAX_LEN <= 5000
