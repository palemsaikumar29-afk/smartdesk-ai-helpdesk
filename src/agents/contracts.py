"""Typed contracts for the SmartDesk help-desk pipeline."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["IT", "HR", "Facilities", "Security"]
Priority = Literal["P1", "P2", "P3", "P4"]
Status = Literal["open", "in_progress", "escalated", "resolved", "closed"]


class TriageDecision(BaseModel):
    category: Category
    priority: Priority
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = ""
    reason: str = ""


class KBArticle(BaseModel):
    article_id: int
    category: str
    title: str
    body: str
    score: float = 0.0


class TicketResult(BaseModel):
    ticket_id: int
    category: str
    priority: str
    status: str
    assignee: str
    sla_due: str
    resolution: str = ""
    escalated: bool = False
