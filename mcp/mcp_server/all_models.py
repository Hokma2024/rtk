from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    DENIED = "DENIED"
    FAILED = "FAILED"


class OtrsStatus(str, Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Region(str, Enum):
    COMMON = "COMMON"
    MSK = "MSK"
    SPB = "SPB"
    SIB = "SIB"



class SearchLogsRequest(BaseModel):
    order_id: str = Field(..., description="Идентификатор заказа")
    pattern: str = Field(..., description="Код ошибки или подстрока")
    window_days: int = Field(30, ge=1, le=365)


class SearchLogsResponse(BaseModel):
    error_found: bool
    error_code: Optional[str] = None
    samples: List[str]


class CheckEissdStatusRequest(BaseModel):
    order_id: str


class CheckEissdStatusResponse(BaseModel):
    status: OrderStatus
    raw: Dict[str, Any]


class UpdateOrderStatusRequest(BaseModel):
    order_id: str
    new_status: OrderStatus


class UpdateOrderStatusResponse(BaseModel):
    updated: bool
    old_status: Optional[OrderStatus] = None
    new_status: Optional[OrderStatus] = None



class ResolveMrfQueueRequest(BaseModel):
    region: Region = Region.COMMON


class ResolveMrfQueueResponse(BaseModel):
    queue: str


class AddOtrsCommentRequest(BaseModel):
    ticket_id: str
    text: str = Field(..., min_length=1, max_length=2000)


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
    status: OtrsStatus
    assignee: Optional[str] = None


class UpdateOtrsTicketResponse(BaseModel):
    ok: bool
    ticket: Dict[str, Any]