from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RagRequest(BaseModel):
    ticket_id: str
    order_id: str
    subject: str
    annotation: str
    description: str
    region: str = "COMMON"
    precheck: dict[str, Any] = Field(default_factory=dict)


class RagResponse(BaseModel):
    required_actions: list[dict[str, Any]] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
