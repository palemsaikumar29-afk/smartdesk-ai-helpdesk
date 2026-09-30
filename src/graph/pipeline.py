"""LangGraph pipeline: intake -> triage -> kb_search -> resolve (terminal)."""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from ..agents.contracts import TriageDecision
from ..agents.nodes import intake_node, kb_node, resolve_node, triage_node
from ..database.db import ensure_seeded, get_conn, utcnow


class DeskState(TypedDict, total=False):
    title: str
    description: str
    clean_title: str
    clean_description: str
    injection: bool
    injection_patterns: list[str]
    pii_kinds: list[str]
    triage: TriageDecision
    articles: list[dict]
    ticket_id: int
    resolution: str
    escalated: bool
    offline: bool
    status: str


def build_pipeline():
    g = StateGraph(DeskState)
    g.add_node("intake", intake_node)
    g.add_node("triage", triage_node)
    g.add_node("kb_search", kb_node)
    g.add_node("resolve", resolve_node)
    g.set_entry_point("intake")
    g.add_edge("intake", "triage")
    g.add_edge("triage", "kb_search")
    g.add_edge("kb_search", "resolve")
    g.add_edge("resolve", END)
    return g.compile()


def sla_sweep() -> list[dict]:
    """Escalate open tickets past their SLA due time. Returns escalated rows."""
    ensure_seeded()
    now = utcnow()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT ticket_id FROM tickets WHERE status = 'open'"
            " AND sla_due < ?", (now,),
        ).fetchall()
        ids = [r["ticket_id"] for r in rows]
        for tid in ids:
            conn.execute("UPDATE tickets SET status = 'escalated'"
                         " WHERE ticket_id = ?", (tid,))
        conn.commit()
    finally:
        conn.close()
    from ..database.db import log_event

    for tid in ids:
        log_event(tid, "sla_escalated", "SLA breached")
    return [{"ticket_id": tid} for tid in ids]


def submit_ticket(title: str, description: str) -> dict[str, Any]:
    """Run one help-desk turn; returns the final result dict."""
    ensure_seeded()
    app = build_pipeline()
    result = app.invoke({"title": title, "description": description})
    triage: TriageDecision = result.get("triage")
    return {
        "ticket_id": result.get("ticket_id"),
        "category": triage.category if triage else "unknown",
        "priority": triage.priority if triage else "unknown",
        "status": result.get("status", "open"),
        "resolution": result.get("resolution", ""),
        "articles": [a["title"] for a in result.get("articles", [])],
        "offline": result.get("offline", True),
        "escalated": result.get("escalated", False),
        "injection": result.get("injection", False),
        "pii_kinds": result.get("pii_kinds", []),
    }
