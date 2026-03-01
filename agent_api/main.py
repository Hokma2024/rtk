from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from common.config import get_settings
from common.metrics import agent_latency_seconds, agent_requests_total
from common.models import Ticket
from clients.mcp_client import MCPClient
from pipeline.pipeline import (
    precheck_logs,
    call_rag,
    plan_and_execute,
    verify_final_status,
    build_final_comment,
    finalize,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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


def get_mcp(request: Request) -> MCPClient:
    return request.app.state.mcp


class TicketIn(BaseModel):
    id: str = Field(..., description="OTRS ticket id")
    order_id: str
    subject: str = ""
    annotation: str = ""
    description: str
    region: str = "COMMON"
    queue: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TicketOut(BaseModel):
    ticket_id: str
    final_comment: str
    summary: str
    actions: Optional[List[Dict[str, Any]]] = None


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/tickets/intake", response_model=TicketOut)
async def intake(ticket_in: TicketIn, mcp: MCPClient = Depends(get_mcp)):
    settings = get_settings()
    t0 = time.monotonic()
    deadline = t0 + settings.request_time_budget_seconds

    with agent_latency_seconds.labels(endpoint="/tickets/intake").time():
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

            # Шаг 2: precheck
            ctx: Dict[str, Any] = await precheck_logs(ticket, mcp, deadline=deadline)

            # Шаг 3-4: RAG schema + контекст
            ctx.update(await call_rag(ticket, ctx, deadline=deadline))

            # Шаг 4-5: LLM/tool-loop (без финального текста)
            actions = await plan_and_execute(ticket, ctx, mcp, deadline=deadline)

            # Шаг 5: цикл финальной проверки статуса (политика агента)
            verify, verify_actions = await verify_final_status(ticket, mcp, deadline=deadline)
            actions_all = actions + verify_actions

            # Шаг 6: детерминированный финальный комментарий
            final_comment = build_final_comment(
                ticket,
                precheck=ctx.get("precheck") or {},
                rag=ctx.get("rag"),
                actions=actions_all,
                verify=verify,
            )

            # Шаг 7: финализация тикета
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

            agent_requests_total.labels(endpoint="/tickets/intake", status="200").inc()
            return TicketOut(ticket_id=ticket.id, final_comment=final_comment, summary=summary, actions=actions_json)

        except TimeoutError as exc:
            agent_requests_total.labels(endpoint="/tickets/intake", status="504").inc()
            raise HTTPException(status_code=504, detail=str(exc))
        except Exception as exc:
            logger.exception("processing failed: %s", exc)
            agent_requests_total.labels(endpoint="/tickets/intake", status="500").inc()
            raise HTTPException(status_code=500, detail=str(exc))
