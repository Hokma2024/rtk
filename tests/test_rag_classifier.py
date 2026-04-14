"""Юнит-тесты классификатора rag_adapter на реальных и синтетических кейсах."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.rag_adapter.classifier import (
    classify_rag_response,
    extract_order_ids,
)

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "rag_real_responses.json"


def load_fixtures() -> list[dict]:
    with FIXTURES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.unit
@pytest.mark.parametrize("case", load_fixtures(), ids=lambda c: c["id"])
def test_classify_matches_expected_type(case: dict) -> None:
    result = classify_rag_response(case["raw_answer"], case["current_order_id"])
    assert result == case["expected_type"], (
        f"Case {case['id']}: expected {case['expected_type']}, got {result}"
    )


@pytest.mark.unit
def test_classify_empty_string() -> None:
    assert classify_rag_response("", "1800003858739") == "empty"


@pytest.mark.unit
def test_classify_whitespace_only() -> None:
    assert classify_rag_response("   \n\t  ", "1800003858739") == "empty"


@pytest.mark.unit
def test_classify_very_short() -> None:
    assert classify_rag_response("Нет данных", "1800003858739") == "empty"


@pytest.mark.unit
def test_classify_direct_single_order() -> None:
    text = (
        "Рекомендация: перевести заявку 1800003879409 в статус Отказ в ЕИССД "
        "и проверить серийные номера."
    )
    assert classify_rag_response(text, "1800003879409") == "direct"


@pytest.mark.unit
def test_classify_batch_many_order_ids() -> None:
    text = (
        "1. Для 1111111111 перевести в отказ. "
        "2. Для 2222222222 проверить статус. "
        "3. Для 3333333333 высвободить серийник. "
        "4. Для 4444444444 закрыть заявку."
    )
    assert classify_rag_response(text, "5555555555") == "batch_historical"


@pytest.mark.unit
def test_classify_documentation_by_section_marker() -> None:
    text = (
        "Изменение параметров в п. 3.5.25 Получение условий доставки. "
        "Обновить параметры ответа согласно изменениям. Автор: Савельева Е. Ю."
    )
    assert classify_rag_response(text, "1800003879409") == "documentation"


@pytest.mark.unit
def test_extract_order_ids_unique_ordered() -> None:
    text = "1111111111, 2222222222, 1111111111, 3333333333"
    assert extract_order_ids(text) == ["1111111111", "2222222222", "3333333333"]


@pytest.mark.unit
def test_extract_order_ids_empty_text() -> None:
    assert extract_order_ids("") == []
    assert extract_order_ids("нет заявок") == []
