from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class RagRequest(BaseModel):
    ticket_id: str
    order_id: str
    subject: str
    annotation: str
    description: str
    precheck: Dict[str, Any] = Field(default_factory=dict)


class RagResponse(BaseModel):
    required_actions: List[Dict[str, Any]] = Field(default_factory=list)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    parameters: Dict[str, Any] = Field(default_factory=dict)
