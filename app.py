"""Gradio UI: submit ticket, knowledge base, dashboard."""
from __future__ import annotations

import gradio as gr

from src.database.db import get_conn, log_event
from src.graph.pipeline import sla_sweep, submit_ticket
from src.services import kb
from src.services.llm_factory import provider_status

_LAST: dict = {}


def do_submit(title: str, description: str) -> str:
    if not title.strip() or not description.strip():
        return "Please fill in both a title and a description."
    result = submit_ticket(title.strip(), description.strip())
    _LAST.update(result)
    badge = " 🟠 offline" if result["offline"] else " 🟢 live LLM"
    return (
        f"### Ticket #{result['ticket_id']} created\n"
        f"- Category: **{result['category']}** · Priority: **{result['priority']}**"
        f" · Status: **{result['status']}**{badge}\n"
        f"- Suggested resolution:\n{result['resolution']}\n"
        f"- KB matches: {', '.join(result['articles']) or 'none'}"
    )


def do_kb_search(query: str, category: str) -> str:
    hits = kb.search_kb(query, category=None if category == "All" else category)
    if not hits:
        return "No relevant article found in the knowledge base."
    return "\n\n".join(
        f"**{h['title']}** ({h['category']})\n{h['body']}" for h in hits)


def do_sweep() -> str:
    escalated = sla_sweep()
    if not escalated:
        return "No SLA breaches — nothing escalated."
    return "Escalated: " + ", ".join(f"#{e['ticket_id']}" for e in escalated)


def dashboard() -> list[list]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT ticket_id, title, category, priority, status, assignee,"
            " created_at FROM tickets ORDER BY ticket_id DESC LIMIT 50"
        ).fetchall()
    finally:
        conn.close()
    return [[r["ticket_id"], r["title"][:50], r["category"], r["priority"],
             r["status"], r["assignee"], r["created_at"][:16]] for r in rows]


def resolve_ticket(ticket_id: int, note: str) -> str:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE tickets SET status = 'resolved', resolution = ?"
            " WHERE ticket_id = ?",
            (note, int(ticket_id)),
        )
        conn.commit()
    finally:
        conn.close()
    log_event(int(ticket_id), "resolved", note[:200])
    return f"Ticket #{ticket_id} marked resolved."


def status_line() -> str:
    provider, model, key_present, reason = provider_status()
    if key_present:
        return f"LLM: {provider}/{model} — live"
    return f"LLM: {provider} — offline ({reason}); keyword triage + templates"


def build_app() -> gr.Blocks:
    with gr.Blocks(title="SmartDesk AI — Help Desk") as app:
        gr.Markdown("# 🛎️ SmartDesk AI — IT/HR Help Desk\n"
                    "Multi-agent triage over tickets and the knowledge base.")
        with gr.Tab("Submit ticket"):
            title = gr.Textbox(label="Title",
                               placeholder="e.g. VPN not connecting on MacBook")
            desc = gr.Textbox(label="Description", lines=4,
                              placeholder="Describe the issue in detail…")
            out = gr.Markdown()
            btn = gr.Button("Submit", variant="primary")
            btn.click(do_submit, [title, desc], out)
        with gr.Tab("Knowledge base"):
            q = gr.Textbox(label="Search",
                           placeholder="e.g. how do I reset my password?")
            cat = gr.Dropdown(["All", "IT", "HR", "Facilities", "Security"],
                              value="All", label="Category")
            kb_out = gr.Markdown()
            q.submit(do_kb_search, [q, cat], kb_out)
        with gr.Tab("Dashboard"):
            gr.Markdown(value=status_line())
            table = gr.Dataframe(
                headers=["id", "title", "category", "priority", "status",
                         "assignee", "created"],
                label="Tickets")
            with gr.Row():
                refresh = gr.Button("Refresh")
                sweep = gr.Button("Run SLA sweep")
            sweep_out = gr.Markdown()
            refresh.click(dashboard, outputs=table)
            sweep.click(do_sweep, outputs=sweep_out)
            with gr.Row():
                tid = gr.Number(label="Ticket id", precision=0)
                note = gr.Textbox(label="Resolution note")
                res = gr.Button("Mark resolved")
            res_out = gr.Markdown()
            res.click(resolve_ticket, [tid, note], res_out)
    return app


if __name__ == "__main__":
    build_app().launch(server_name="0.0.0.0",
                       server_port=int(os.environ.get("PORT", 7862)))
