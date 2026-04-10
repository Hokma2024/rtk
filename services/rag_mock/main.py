"""Мок-сервис RAG — возвращает детерминированные планы действий для тестирования."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response as _PromResponse

from common.config import get_settings
from common.logging import configure_logging, get_logger
from common.metrics import rag_requests_total
from common.middleware import TraceIdMiddleware, install_http_metrics
from pipeline.rag_models import RagRequest, RagResponse

_settings = get_settings()
_SERVICE_NAME = "rag_mock"
configure_logging(_SERVICE_NAME)
log = get_logger(__name__)

app = FastAPI(title="RAG Mock")

app.add_middleware(TraceIdMiddleware)
install_http_metrics(app, service_name=_SERVICE_NAME)


@app.get("/metrics")
def metrics_endpoint() -> _PromResponse:
    return _PromResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/query", response_model=RagResponse)
async def query(req: RagRequest) -> RagResponse:
    try:
        pre = req.precheck or {}
        logs = pre.get("logs") or {}
        error_found = bool(logs.get("error_found")) if isinstance(logs, dict) else False

        required_actions: list[dict[str, Any]]
        if error_found:
            region = req.region or "COMMON"
            required_actions = [
                {"tool": "get_order_status", "arguments": {"order_id": req.order_id}},
                {"tool": "check_eissd_status", "arguments": {"order_id": req.order_id}},
                {"tool": "check_edit_order_request", "arguments": {"order_id": req.order_id}},
                {"tool": "resolve_mrf_queue", "arguments": {"region": region}},
                {
                    "tool": "mrf_process_ticket",
                    "arguments": {
                        "ticket_id": req.ticket_id,
                        "order_id": req.order_id,
                        "region": region,
                    },
                },
                {"tool": "list_otrs_comments", "arguments": {"ticket_id": req.ticket_id}},
            ]
        else:
            required_actions = [
                {"tool": "check_eissd_status", "arguments": {"order_id": req.order_id}},
            ]

        result = RagResponse(
            required_actions=required_actions,
            conditions={
                "error_found": error_found,
                "error_code": logs.get("error_code") if isinstance(logs, dict) else None,
            },
            parameters={
                "ticket_id": req.ticket_id,
                "subject": req.subject,
                "annotation": req.annotation,
            },
        )
        rag_requests_total.labels(status="ok").inc()
        return result
    except Exception:
        # Пробрасываем дальше после логирования; FastAPI сам превратит в 500
        log.exception("rag_query_error", order_id=req.order_id)
        rag_requests_total.labels(status="error").inc()
        raise
