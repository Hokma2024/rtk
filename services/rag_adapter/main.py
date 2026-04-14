"""FastAPI-приложение rag_adapter.

Принимает запросы в стандартном контракте ``RagRequest`` и отдаёт
расширенный ``RagResponse`` с полями ``answer_text``, ``sources`` и
диагностикой в ``parameters``. Внутри:

1. Вызывает реальный RAG через ``client.call_real_rag``.
2. Классифицирует ответ (``classifier.classify_rag_response``).
3. Фильтрует текст под тип (``filter.filter_rag_response``).
4. Возвращает ``RagResponse`` с пустым ``required_actions`` и заполненным
   текстом — LLM-агент получит контекст в свой system prompt.

Полный сырой ответ RAG логируется для аудита (по trace_id), в контекст
пайплайна попадает только отфильтрованный текст, чтобы не раздувать
контекст LLM.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response as _PromResponse

from common.logging import configure_logging, get_logger
from common.metrics import rag_requests_total
from common.middleware import TraceIdMiddleware, install_http_metrics
from pipeline.rag_models import RagRequest, RagResponse

from . import client as real_client
from .classifier import classify_rag_response, extract_order_ids
from .filter import filter_rag_response

_SERVICE_NAME = "rag_adapter"
configure_logging(_SERVICE_NAME)
log = get_logger(__name__)

app = FastAPI(title="RAG Adapter")

app.add_middleware(TraceIdMiddleware)
install_http_metrics(app, service_name=_SERVICE_NAME)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/metrics")
def metrics_endpoint() -> _PromResponse:
    return _PromResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/query", response_model=RagResponse)
async def query(req: RagRequest) -> RagResponse:
    """Обрабатывает запрос к реальному RAG и возвращает отфильтрованный ответ."""
    try:
        raw = await real_client.call_real_rag(req)
    except real_client.RealRagNotConfiguredError as exc:
        # Мягкая деградация: адаптер поднят, но REAL_RAG_URL не задан.
        # Возвращаем пустой ответ — агент уйдёт в fallback по precheck.
        log.warning("real_rag_not_configured", error=str(exc))
        rag_requests_total.labels(status="ok").inc()
        return RagResponse(
            required_actions=[],
            conditions={},
            parameters={
                "rag_relevance": "empty",
                "rag_full_length": 0,
                "rag_filtered_length": 0,
                "rag_order_ids_found": [],
                "rag_matched_current_order": False,
                "cached": False,
                "rag_error": "not_configured",
            },
            answer_text=None,
            sources=[],
        )
    except Exception as exc:
        log.exception("real_rag_call_failed", error=str(exc))
        rag_requests_total.labels(status="error").inc()
        raise HTTPException(status_code=502, detail=f"real rag call failed: {exc}") from exc

    raw_answer = str(raw.get("answer") or "")
    raw_sources = raw.get("source") or []
    if not isinstance(raw_sources, list):
        raw_sources = []
    cached = bool(raw.get("cached", False))

    # Полный сырой ответ — в лог, в контекст пайплайна только отфильтрованный.
    log.info(
        "real_rag_raw_response",
        order_id=req.order_id,
        full_length=len(raw_answer),
        sources_count=len(raw_sources),
        cached=cached,
        preview=raw_answer[:500],
    )

    kind = classify_rag_response(raw_answer, req.order_id)
    filtered = filter_rag_response(kind, raw_answer, req.order_id)
    order_ids_found = extract_order_ids(raw_answer)
    matched_current = req.order_id in order_ids_found

    log.info(
        "rag_adapter_filtered",
        order_id=req.order_id,
        relevance=kind,
        full_length=len(raw_answer),
        filtered_length=len(filtered),
        order_ids_count=len(order_ids_found),
        matched_current_order=matched_current,
    )

    result = RagResponse(
        required_actions=[],
        conditions={
            "rag_relevance": kind,
            "matched_current_order": matched_current,
        },
        parameters={
            "rag_relevance": kind,
            "rag_full_length": len(raw_answer),
            "rag_filtered_length": len(filtered),
            "rag_order_ids_found": order_ids_found[:20],
            "rag_matched_current_order": matched_current,
            "cached": cached,
        },
        answer_text=filtered or None,
        sources=[s for s in raw_sources if isinstance(s, dict)],
    )
    rag_requests_total.labels(status="ok").inc()
    return result
