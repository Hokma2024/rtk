from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field
from starlette.responses import Response as _PromResponse

from clients.mcp_client import MCPClient
from common.config import get_settings
from common.logging import configure_logging, get_logger
from common.middleware import TraceIdMiddleware, install_http_metrics
from common.models import Ticket
from pipeline.pipeline import (
    _evaluate_llm_outcome,
    build_final_comment,
    call_rag,
    finalize,
    mrf_roundtrip,
    plan_and_execute,
    precheck_logs,
    verify_final_status,
)

_SERVICE_NAME = os.getenv("SERVICE_NAME", "agent_api")
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
configure_logging(_SERVICE_NAME, _LOG_LEVEL)
log = get_logger(__name__)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    mcp = MCPClient(server_module=settings.mcp_server_module)
    await mcp.connect()
    app.state.mcp = mcp
    yield
    mcp2: MCPClient = getattr(app.state, "mcp", None)
    if mcp2:
        await mcp2.close()


app = FastAPI(title="Unified RTK Agent API", lifespan=lifespan)

app.add_middleware(TraceIdMiddleware)
install_http_metrics(app, service_name=_SERVICE_NAME)


@app.on_event("startup")
async def _log_startup() -> None:
    log.info("service_startup", service=_SERVICE_NAME)


@app.on_event("shutdown")
async def _log_shutdown() -> None:
    log.info("service_shutdown", service=_SERVICE_NAME)


def get_mcp(request: Request) -> MCPClient:
    return request.app.state.mcp


class TicketIn(BaseModel):
    id: str = Field(..., description="Идентификатор OTRS-тикета")
    order_id: str
    subject: str = ""
    annotation: str = ""
    description: str
    region: str = "COMMON"
    queue: str | None = None
    metadata: dict[str, Any] | None = None


class TicketOut(BaseModel):
    ticket_id: str
    final_comment: str
    summary: str
    actions: list[dict[str, Any]] | None = None


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/metrics")
def metrics_endpoint() -> _PromResponse:
    return _PromResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/tickets/intake", response_model=TicketOut)
async def intake(ticket_in: TicketIn, mcp: MCPClient = Depends(get_mcp)) -> TicketOut:  # noqa: B008
    """Обрабатывает входящий OTRS-тикет через полный конвейер агента."""
    settings = get_settings()
    t0 = time.monotonic()
    deadline = t0 + settings.request_time_budget_seconds

    try:
        ticket = Ticket(
            id=ticket_in.id,
            order_id=ticket_in.order_id,
            subject=ticket_in.subject or "",
            annotation=ticket_in.annotation or "",
            description=ticket_in.description,
            region=(ticket_in.region or "COMMON"),
            queue=ticket_in.queue,
            created_at=datetime.utcnow(),
            metadata=ticket_in.metadata or {},
        )

        ctx: dict[str, Any] = await precheck_logs(ticket, mcp, deadline=deadline)
        ctx.update(await call_rag(ticket, ctx, deadline=deadline))
        actions = await plan_and_execute(ticket, ctx, mcp, deadline=deadline)
        escalate_triggered, escalate_reasons = _evaluate_llm_outcome(actions, ctx)
        ctx["escalate_reasons_pre_verify"] = escalate_reasons

        # Шаги 5.1–5.3: детерминированный цикл МРФ (resolve → process → analyze comments).
        # Повторный RAG после возврата МРФ (шаг 5.4) намеренно не выполняется.
        mrf_ctx, mrf_actions = await mrf_roundtrip(ticket, mcp, deadline=deadline)

        verify, verify_actions = await verify_final_status(ticket, mcp, deadline=deadline)
        actions_all = actions + mrf_actions + verify_actions

        final_comment = build_final_comment(
            ticket,
            precheck=ctx.get("precheck") or {},
            rag=ctx.get("rag"),
            actions=actions_all,
            verify=verify,
            llm_metrics=ctx.get("llm_metrics"),
            escalate_reasons=list(escalate_reasons),
            mrf=mrf_ctx,
        )

        finalize_logs = await finalize(ticket, final_comment, mcp, deadline=deadline)

        summary = final_comment.split("\n", 1)[0] if final_comment else ""

        actions_json = None
        if settings.debug:
            actions_json = [
                {
                    "tool": a.tool,
                    "params": a.params,
                    "ok": a.ok,
                    "error": a.error,
                    "error_type": a.error_type,
                    "duration_ms": a.duration_ms,
                }
                for a in (actions_all + (finalize_logs or []))
            ]

        return TicketOut(ticket_id=ticket.id, final_comment=final_comment, summary=summary, actions=actions_json)

    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("processing failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
