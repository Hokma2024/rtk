from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List

from pipeline.rag_models import RagRequest, RagResponse

app = FastAPI(title="RAG Mock")


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/query", response_model=RagResponse)
async def query(req: RagRequest):
    # Очень простой mock: если precheck обнаружил ORDER_STATUS_DENIED, предлагаем стандартные проверки.
    pre = req.precheck or {}
    logs = pre.get("logs") or {}
    error_found = bool(logs.get("error_found")) if isinstance(logs, dict) else False

    required_actions: List[Dict[str, Any]] = []
    if error_found:
        required_actions = [
            {"tool": "get_order_status", "arguments": {"order_id": req.order_id}},
            {"tool": "check_eissd_status", "arguments": {"order_id": req.order_id}},
            {"tool": "check_edit_order_request", "arguments": {"order_id": req.order_id}},
        ]
    else:
        required_actions = [
            {"tool": "check_eissd_status", "arguments": {"order_id": req.order_id}},
        ]

    return RagResponse(
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
