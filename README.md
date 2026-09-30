# SmartDesk AI — IT/HR Help Desk

Capstone Agent 5 (Interview Kickstart Applied Agentic AI). A multi-agent
help-desk system: incoming tickets are triaged (IT / HR / Facilities /
Security + P1–P4 priority), matched against a seeded knowledge base, given
a drafted resolution, and escalated on SLA breach — with prompt-injection
detection and PII redaction on every ticket *before* any LLM call.

## Architecture

```
ticket (title + description)
      │
      ▼
┌─ intake ─────────────── 26 injection patterns; PII redaction
├─ triage ─────────────── LLM triage (structured CATEGORY/PRIORITY/
│                         CONFIDENCE/SUMMARY) with deterministic keyword
│                         triage fallback in offline mode
├─ kb_search ──────────── token-overlap search over 13 seeded IT/HR articles
└─ resolve ────────────── creates the ticket, assigns the right team queue,
                          drafts a resolution, marks P1 / injection tickets
                          escalated
      │                                    │
      ▼                                    ▼
terminal: open (+draft resolution)   terminal: escalated
SLA sweep escalates open tickets past their sla_due (P1 4h, P2 8h, P3 24h, P4 72h).
```

### Five layers (`src/`)

| Layer | Contents |
|---|---|
| `ui` | `app.py`: Gradio 5.x — **Submit ticket** tab, **Knowledge base** search tab, **Dashboard** tab (tickets, SLA sweep, mark-resolved) |
| `services/` | env-only config, multi-provider LLM factory (OpenAI/Gemini/Groq), injection detection, PII redaction, KB token-overlap search |
| `agents/` | Pydantic contracts (`TriageDecision`, `KBArticle`, `TicketResult`) + intake/triage/KB/resolve nodes |
| `graph/` | annotated `DeskState` TypedDict + LangGraph pipeline; `submit_ticket()` and `sla_sweep()` entry points |
| `database/` | SQLite: `tickets`, `kb_articles` (13 seeded), append-only `audit_log` |

## LLM providers

One env var switches providers — OpenAI, Gemini 2.0 Flash, or Groq
`openai/gpt-oss-20b`. Provider, model, key, and timeout all come from the
environment (see `.env.example`); nothing is hardcoded. With no key set, the
pipeline runs in clearly-labelled offline mode (keyword triage + template
resolutions). Retries use exponential backoff (3 attempts).

## Quickstart

```bash
make install          # create .venv and install pinned requirements
make seed             # create + seed the SQLite help-desk database
cp .env.example .env  # fill in at least one LLM API key
make test             # 19 unit + e2e tests (no network, no keys needed)
make lint             # ruff
make run              # launch the Gradio app on 127.0.0.1:7862
```

## Test evidence

- `make test`: **19 passed** — KB seeding, token-overlap KB search
  (category filtering, no-match), keyword triage per category and priority
  (including P1 outage and security-incident escalation), e2e ticket
  submission per category, injection-blocked tickets routed to Security,
  PII redaction, SLA sweep (overdue escalated, fresh untouched), audit-log
  writes.
- `make test-all` additionally runs live-LLM triage checks (skipped without
  keys) and a Gradio app startup smoke test.
- `make lint`: ruff clean.

## Honest limits

- The knowledge base and ticket data are synthetic demo content, not a live
  ITSM system; there is no email/Slack integration.
- The keyword triage is a deterministic fallback; production would use the
  LLM triage with evaluation on labelled tickets.
- Built from the published capstone brief for this project; the UpLevel
  portal spec was not re-fetched during this build.
