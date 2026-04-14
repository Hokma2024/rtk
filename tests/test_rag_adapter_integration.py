"""Интеграционный тест rag_adapter через FastAPI TestClient.

Реальный RAG не вызывается — ``services.rag_adapter.client.call_real_rag``
подменяется через monkeypatch. Тест проверяет, что адаптер:

1. Корректно собирает ``RagResponse`` для всех типов ответов.
2. Прокидывает ``sources`` и ``cached`` из сырого ответа.
3. Гладко деградирует, если ``REAL_RAG_URL`` не сконфигурирован.
4. Возвращает HTTP 502 при ошибке вызова реального RAG.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from services.rag_adapter import client as real_client_module
from services.rag_adapter.main import app

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "rag_real_responses.json"


def load_fixtures() -> list[dict]:
    with FIXTURES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _fixture_by_id(fixture_id: str) -> dict:
    for case in load_fixtures():
        if case["id"] == fixture_id:
            return case
    raise KeyError(fixture_id)


def _make_request_payload(order_id: str) -> dict[str, Any]:
    return {
        "ticket_id": "T-TEST",
        "order_id": order_id,
        "subject": "Заявка уже отправлена в СУЛЗ",
        "annotation": f"Юг; СУЛЗ. Заявка уже отправлена в СУЛЗ;{order_id}",
        "description": "Описание ошибки ORDER_STATUS_DENIED",
        "region": "Юг",
        "precheck": {},
    }


@pytest.fixture
def client() -> TestClient:
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.integration
def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.integration
def test_metrics(client: TestClient) -> None:
    resp = client.get("/metrics")
    assert resp.status_code == 200
    # Метрика rag_requests_total регистрируется при импорте common.metrics.
    assert "text/plain" in resp.headers.get("content-type", "")


@pytest.mark.integration
def test_query_direct_case(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """direct: текст должен содержать current_order_id, sources прокидываются."""
    case = _fixture_by_id("case_2_direct")
    fake = AsyncMock(
        return_value={
            "answer": case["raw_answer"],
            "source": case["sources"],
            "cached": False,
        }
    )
    monkeypatch.setattr(real_client_module, "call_real_rag", fake)

    resp = client.post("/query", json=_make_request_payload(case["current_order_id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert body["required_actions"] == []
    assert body["parameters"]["rag_relevance"] == "direct"
    assert body["parameters"]["rag_full_length"] == len(case["raw_answer"])
    assert body["parameters"]["rag_filtered_length"] > 0
    assert body["parameters"]["rag_matched_current_order"] is True
    assert body["parameters"]["cached"] is False
    assert body["conditions"]["rag_relevance"] == "direct"
    assert body["conditions"]["matched_current_order"] is True
    assert body["answer_text"] is not None
    assert case["current_order_id"] in body["answer_text"]
    # sources пробрасываются как есть.
    assert body["sources"] == case["sources"]

    fake.assert_awaited_once()


@pytest.mark.integration
def test_query_documentation_returns_empty_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """documentation: фильтр очищает текст до пустого, answer_text=None."""
    case = _fixture_by_id("case_1_documentation")
    fake = AsyncMock(
        return_value={
            "answer": case["raw_answer"],
            "source": case["sources"],
            "cached": True,
        }
    )
    monkeypatch.setattr(real_client_module, "call_real_rag", fake)

    resp = client.post("/query", json=_make_request_payload(case["current_order_id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert body["parameters"]["rag_relevance"] == "documentation"
    assert body["parameters"]["rag_full_length"] == len(case["raw_answer"])
    assert body["parameters"]["rag_filtered_length"] == 0
    assert body["parameters"]["cached"] is True
    # Пустой отфильтрованный текст → answer_text=None.
    assert body["answer_text"] is None
    # Источники всё равно прокидываются — агент может решить упомянуть их.
    assert body["sources"] == case["sources"]


@pytest.mark.integration
def test_query_batch_historical_normalizes_foreign_orders(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """batch_historical: чужие order_id не должны утекать в answer_text."""
    case = _fixture_by_id("case_3_batch_historical")
    fake = AsyncMock(
        return_value={
            "answer": case["raw_answer"],
            "source": case["sources"],
            "cached": False,
        }
    )
    monkeypatch.setattr(real_client_module, "call_real_rag", fake)

    resp = client.post("/query", json=_make_request_payload(case["current_order_id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert body["parameters"]["rag_relevance"] == "batch_historical"
    assert body["parameters"]["rag_matched_current_order"] is False
    assert body["answer_text"] is not None
    # Чужие order_id заменены плейсхолдером.
    import re

    foreign = [
        x
        for x in re.findall(r"\b\d{10,15}\b", body["answer_text"])
        if x != case["current_order_id"]
    ]
    assert not foreign, f"foreign order_ids leaked: {foreign}"
    # В parameters собирается полный список найденных id из сырого текста (до 20).
    assert len(body["parameters"]["rag_order_ids_found"]) >= 4


@pytest.mark.integration
def test_query_current_order_in_batch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Текущий order_id присутствует в пакетном ответе — должен сохраниться."""
    case = _fixture_by_id("case_7_current_order_in_batch")
    fake = AsyncMock(
        return_value={
            "answer": case["raw_answer"],
            "source": case["sources"],
            "cached": False,
        }
    )
    monkeypatch.setattr(real_client_module, "call_real_rag", fake)

    resp = client.post("/query", json=_make_request_payload(case["current_order_id"]))
    assert resp.status_code == 200
    body = resp.json()

    assert body["parameters"]["rag_relevance"] == "batch_historical"
    assert body["parameters"]["rag_matched_current_order"] is True
    assert case["current_order_id"] in body["answer_text"]


@pytest.mark.integration
def test_query_empty_raw_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пустой сырой ответ — адаптер возвращает answer_text=None, relevance=empty."""
    fake = AsyncMock(return_value={"answer": "", "source": [], "cached": False})
    monkeypatch.setattr(real_client_module, "call_real_rag", fake)

    resp = client.post("/query", json=_make_request_payload("1800003858739"))
    assert resp.status_code == 200
    body = resp.json()

    assert body["parameters"]["rag_relevance"] == "empty"
    assert body["parameters"]["rag_full_length"] == 0
    assert body["parameters"]["rag_filtered_length"] == 0
    assert body["answer_text"] is None
    assert body["sources"] == []


@pytest.mark.integration
def test_query_real_rag_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если REAL_RAG_URL не задан — мягкая деградация, 200 с rag_error."""

    async def _raise(*_args, **_kwargs):
        raise real_client_module.RealRagNotConfiguredError("REAL_RAG_URL is not set")

    monkeypatch.setattr(real_client_module, "call_real_rag", _raise)

    resp = client.post("/query", json=_make_request_payload("1800003858739"))
    assert resp.status_code == 200
    body = resp.json()

    assert body["parameters"]["rag_relevance"] == "empty"
    assert body["parameters"]["rag_error"] == "not_configured"
    assert body["answer_text"] is None
    assert body["sources"] == []
    assert body["required_actions"] == []


@pytest.mark.integration
def test_query_real_rag_call_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сетевые / HTTP ошибки превращаются в 502."""

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(real_client_module, "call_real_rag", _boom)

    resp = client.post("/query", json=_make_request_payload("1800003858739"))
    assert resp.status_code == 502
    assert "real rag call failed" in resp.json()["detail"]


@pytest.mark.integration
def test_query_sources_non_list_is_ignored(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если реальный RAG вернул source не-списком — считаем пустым."""
    fake = AsyncMock(
        return_value={
            "answer": "Рекомендация: перевести заявку 1800003879409 в отказ в ЕИССД.",
            "source": "not-a-list",
            "cached": False,
        }
    )
    monkeypatch.setattr(real_client_module, "call_real_rag", fake)

    resp = client.post("/query", json=_make_request_payload("1800003879409"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"] == []
