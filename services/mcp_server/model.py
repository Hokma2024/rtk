from pydantic import BaseModel
from typing import List, Dict, Any, Optional

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