"""Pipeline nodes: intake -> triage -> kb_search -> resolve -> sla_check."""
from __future__ import annotations

from ..database.db import create_ticket, get_conn, log_event
from ..services import kb
from ..services.llm_factory import call_llm_with_retry, provider_status
from ..services.safety import detect_injection, redact_pii
from .contracts import TriageDecision

# --- keyword triage (deterministic fallback) ---------------------------------

_IT_WORDS = {
    "password", "login", "vpn", "laptop", "computer", "wifi", "network",
    "printer", "software", "install", "mfa", "2fa", "email", "outlook",
    "screen", "keyboard", "mouse", "monitor", "server", "phishing",
}
_HR_WORDS = {
    "leave", "vacation", "pto", "payroll", "payslip", "salary", "benefits",
    "insurance", "harassment", "onboarding", "offboarding", "expense",
    "reimbursement", "promotion", "resign",
}
_SECURITY_WORDS = {
    "breach", "hack", "ransomware", "malware", "phishing", "intrusion",
    "vulnerability", "unauthorized access",
}
_FACILITIES_WORDS = {
    "badge", "parking", "desk", "chair", "office", "cafeteria", "ac ",
    "air conditioning", "lighting", "elevator",
}
_P1_WORDS = {
    "outage", "down", "breach", "ransomware", "hack", "urgent", "critical",
    "asap", "production down", "data loss", "security incident",
}
_P2_WORDS = {
    "cannot login", "can't login", "locked out", "payroll", "not working",
    "broken", "deadline", "blocking",
}


def _hit(words: set[str], text: str) -> bool:
    t = text.lower()
    return any(w in t for w in words)


def keyword_triage(title: str, description: str) -> TriageDecision:
    text = f"{title} {description}"
    if _hit(_SECURITY_WORDS, text):
        category = "Security"
    elif _hit(_IT_WORDS, text):
        category = "IT"
    elif _hit(_HR_WORDS, text):
        category = "HR"
    elif _hit(_FACILITIES_WORDS, text):
        category = "Facilities"
    else:
        category = "IT"
    if _hit(_P1_WORDS, text):
        priority, conf = "P1", 0.9
    elif _hit(_P2_WORDS, text):
        priority, conf = "P2", 0.8
    elif _hit(_HR_WORDS, text) and _hit({"payroll", "harassment"}, text):
        priority, conf = "P2", 0.75
    else:
        priority, conf = "P3", 0.6
    return TriageDecision(
        category=category, priority=priority, confidence=conf,
        summary=title[:120], reason="keyword",
    )


def llm_triage(title: str, description: str) -> TriageDecision:
    prompt = (
        "You are an IT/HR help-desk triage agent. Classify the ticket into "
        "category (IT | HR | Facilities | Security) and priority "
        "(P1 critical | P2 high | P3 normal | P4 low).\n"
        "Reply in exactly four lines:\n"
        "CATEGORY: <category>\nPRIORITY: <priority>\n"
        "CONFIDENCE: <0-1>\nSUMMARY: <one-line summary>\n\n"
        f"Title: {title}\nDescription: {description}"
    )
    raw = call_llm_with_retry(prompt)
    category, priority, confidence, summary = "IT", "P3", 0.5, title[:120]
    for line in raw.splitlines():
        line = line.strip()
        head, _, body = line.partition(":")
        head, body = head.strip().upper(), body.strip()
        if head == "CATEGORY" and body in ("IT", "HR", "Facilities", "Security"):
            category = body
        elif head == "PRIORITY" and body in ("P1", "P2", "P3", "P4"):
            priority = body
        elif head == "CONFIDENCE":
            try:
                confidence = max(0.0, min(1.0, float(body)))
            except ValueError:
                pass
        elif head == "SUMMARY" and body:
            summary = body[:120]
    return TriageDecision(category=category, priority=priority,
                          confidence=confidence, summary=summary, reason="llm")


def triage(title: str, description: str) -> TriageDecision:
    _, _, key_present, _ = provider_status()
    if key_present:
        try:
            return llm_triage(title, description)
        except Exception:  # noqa: BLE001 - fall back to keywords
            return keyword_triage(title, description)
    return keyword_triage(title, description)


def draft_resolution(title: str, description: str,
                     articles: list[dict], offline: bool) -> str:
    if not articles:
        return (
            "Thanks — your ticket is logged and an agent will respond within "
            "the SLA window. No matching knowledge-base article was found, "
            "so a human agent will handle this."
        )
    refs = "\n".join(f"- {a['title']}: {a['body'][:160]}..." for a in articles)
    if offline:
        return (
            "Based on our knowledge base *(offline draft)*:\n" + refs +
            "\nTry these steps; reply if it doesn't resolve the issue and an "
            "agent will take over."
        )
    prompt = (
        "You are a help-desk agent. Draft a concise resolution (<=120 words) "
        "for this ticket using ONLY the knowledge-base excerpts below. "
        "If they don't cover it, say so and promise a human follow-up.\n\n"
        f"Title: {title}\nDescription: {description}\n\n"
        "Knowledge base:\n" + "\n".join(
            f"- {a['title']}: {a['body']}" for a in articles)
    )
    try:
        return call_llm_with_retry(prompt)
    except Exception:  # noqa: BLE001
        return "Based on our knowledge base:\n" + refs


# --- node wrappers -----------------------------------------------------------

def intake_node(state: dict) -> dict:
    text = f"{state['title']} {state['description']}"
    is_injection, patterns = detect_injection(text)
    title, _ = redact_pii(state["title"])
    description, pii_kinds = redact_pii(state["description"])
    return {"injection": is_injection, "injection_patterns": patterns,
            "clean_title": title, "clean_description": description,
            "pii_kinds": pii_kinds}


def triage_node(state: dict) -> dict:
    if state.get("injection"):
        return {"triage": TriageDecision(category="Security", priority="P2",
                                         confidence=1.0,
                                         reason="blocked: injection")}
    decision = triage(state["clean_title"], state["clean_description"])
    return {"triage": decision}


def kb_node(state: dict) -> dict:
    decision: TriageDecision = state["triage"]
    articles = kb.search_kb(
        f"{state['clean_title']} {state['clean_description']}",
        category=decision.category if not state.get("injection") else None,
    )
    return {"articles": articles}


def resolve_node(state: dict) -> dict:
    decision: TriageDecision = state["triage"]
    _, _, key_present, _ = provider_status()
    offline = not key_present
    if state.get("injection"):
        ticket_id = create_ticket(
            state["clean_title"][:80] or "Blocked request",
            "Blocked: prompt-injection patterns detected.",
            "Security", "P2", assignee="security-oncall",
        )
        return {"ticket_id": ticket_id, "resolution": "Blocked for security "
                "review — a security agent will follow up.", "escalated": True,
                "offline": offline}
    assignee = ("it-oncall" if decision.category == "IT"
                else "hr-team" if decision.category == "HR"
                else "facilities-team" if decision.category == "Facilities"
                else "security-oncall")
    if decision.priority == "P1":
        status, escalated = "escalated", True
    else:
        status, escalated = "open", False
    ticket_id = create_ticket(state["clean_title"], state["clean_description"],
                              decision.category, decision.priority, assignee)
    conn = get_conn()
    try:
        conn.execute("UPDATE tickets SET status = ? WHERE ticket_id = ?",
                     (status, ticket_id))
        conn.commit()
    finally:
        conn.close()
    log_event(ticket_id, "triaged",
              f"category={decision.category} priority={decision.priority}"
              f" via={decision.reason}")
    resolution = draft_resolution(state["clean_title"],
                                  state["clean_description"],
                                  state.get("articles", []), offline)
    return {"ticket_id": ticket_id, "resolution": resolution,
            "escalated": escalated, "offline": offline, "status": status}
