from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional


app = FastAPI(title="MCP Server (Mock tools)")


# ==============================
# Mock storages
# ==============================

LOGS_DB: Dict[str, List[str]] = {
    "1800003902272": [
        '2025-09-02 02:37:54.156 [http-nio-8080-exec-13] INFO r.r.s.o.c.c.LoggingFilter: '
        'Request POST /orders/close: <request orderId="1800003902272" '
        'orderStatus="ORDER_STATUS_DENIED" orderStatusDateTime="2025-09-02T05:37:53+03:00" '
        'orderStatusExt="44" reqType="SET_ORDER_STATUS"/>'
    ],
    "1800003879400": [
        '2025-09-10 11:10:10.010 INFO some.logger: Request POST /orders/close: <request orderId="1800003879400" orderStatus="OK"/>'
    ],
}

ORDERS_DB: Dict[str, Dict[str, Any]] = {
    "1800003902272": {"status": "DENIED", "comment": "Initial mock status"},
    "1800003879400": {"status": "DENIED", "comment": "Initial mock status"},
}

EISSD_DB: Dict[str, Dict[str, Any]] = {
    "1800003902272": {"status": "IN_PROGRESS"},
    "1800003879400": {"status": "IN_PROGRESS"},
}

OTRS_COMMENTS: List[Dict[str, Any]] = []
OTRS_TICKETS: Dict[str, Dict[str, Any]] = {}


# ==============================
# Models
# ==============================

class SearchLogsRequest(BaseModel):
    order_id: str
    pattern: str
    window_days: int = 30


class SearchLogsResponse(BaseModel):
    error_found: bool
    error_code: Optional[str] = None
    samples: List[str]


class CheckEissdStatusRequest(BaseModel):
    order_id: str


class CheckEissdStatusResponse(BaseModel):
    status: str
    raw: Dict[str, Any]


class UpdateOrderStatusRequest(BaseModel):
    order_id: str
    new_status: str


class UpdateOrderStatusResponse(BaseModel):
    updated: bool
    old_status: Optional[str] = None
    new_status: Optional[str] = None


class ResolveMrfQueueRequest(BaseModel):
    region: str


class ResolveMrfQueueResponse(BaseModel):
    queue: str


class AddOtrsCommentRequest(BaseModel):
    ticket_id: str
    text: str


class AddOtrsCommentResponse(BaseModel):
    ok: bool


class CheckEditOrderRequest(BaseModel):
    order_id: str


class CheckEditOrderResponse(BaseModel):
    has_edit_order: bool
    details: Dict[str, Any]


class UpdateOtrsTicketRequest(BaseModel):
    ticket_id: str
    queue: str
    status: str
    assignee: Any = None


class UpdateOtrsTicketResponse(BaseModel):
    ok: bool
    ticket: Dict[str, Any]


# ==============================
# Tools
# ==============================

@app.post("/mcp/search_logs", response_model=SearchLogsResponse)
def search_logs(req: SearchLogsRequest):
    logs = LOGS_DB.get(req.order_id, [])
    matched = [line for line in logs if req.pattern in line]
    if matched:
        return SearchLogsResponse(error_found=True, error_code=req.pattern, samples=matched)
    return SearchLogsResponse(error_found=False, error_code=None, samples=[])


@app.post("/mcp/check_eissd_status", response_model=CheckEissdStatusResponse)
def check_eissd_status(req: CheckEissdStatusRequest):
    data = EISSD_DB.get(req.order_id)
    if not data:
        raise HTTPException(status_code=404, detail="order not found in EISSD")
    return CheckEissdStatusResponse(status=data["status"], raw=data)


@app.post("/mcp/update_order_status", response_model=UpdateOrderStatusResponse)
def update_order_status(req: UpdateOrderStatusRequest):
    record = ORDERS_DB.get(req.order_id)
    if not record:
        ORDERS_DB[req.order_id] = {"status": req.new_status, "comment": "created by mock"}
        return UpdateOrderStatusResponse(updated=True, old_status=None, new_status=req.new_status)
    old = record.get("status")
    record["status"] = req.new_status
    return UpdateOrderStatusResponse(updated=True, old_status=old, new_status=req.new_status)


@app.post("/mcp/resolve_mrf_queue", response_model=ResolveMrfQueueResponse)
def resolve_mrf_queue(req: ResolveMrfQueueRequest):
    # примитивный маппинг (можно заменить на справочник)
    region = (req.region or "COMMON").strip()
    queue = f"ОЦО.МРФ.Эксплуатация СУЛЗ.{region}"
    return ResolveMrfQueueResponse(queue=queue)


@app.post("/mcp/add_otrs_comment", response_model=AddOtrsCommentResponse)
def add_otrs_comment(req: AddOtrsCommentRequest):
    OTRS_COMMENTS.append({"ticket_id": req.ticket_id, "text": req.text})
    return AddOtrsCommentResponse(ok=True)


@app.post("/mcp/check_edit_order_request", response_model=CheckEditOrderResponse)
def check_edit_order_request(req: CheckEditOrderRequest):
    # Заглушка: по умолчанию нет EDIT_ORDER
    return CheckEditOrderResponse(has_edit_order=False, details={"order_id": req.order_id, "source": "mock"})


@app.post("/mcp/update_otrs_ticket", response_model=UpdateOtrsTicketResponse)
def update_otrs_ticket(req: UpdateOtrsTicketRequest):
    OTRS_TICKETS[req.ticket_id] = {
        "ticket_id": req.ticket_id,
        "queue": req.queue,
        "status": req.status,
        "assignee": req.assignee,
    }
    return UpdateOtrsTicketResponse(ok=True, ticket=OTRS_TICKETS[req.ticket_id])


# ==============================
# Debug endpoints
# ==============================

@app.get("/debug/comments")
def debug_comments():
    return OTRS_COMMENTS


@app.get("/debug/orders")
def debug_orders():
    return ORDERS_DB


@app.get("/debug/otrs_tickets")
def debug_otrs_tickets():
    return OTRS_TICKETS
