"""SQLite help-desk database: tickets, knowledge base, audit log."""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..services.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_articles (
    article_id INTEGER PRIMARY KEY,
    category   TEXT NOT NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    category    TEXT NOT NULL,
    priority    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    assignee    TEXT NOT NULL DEFAULT 'unassigned',
    created_at  TEXT NOT NULL,
    sla_due     TEXT NOT NULL,
    resolution  TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    log_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER,
    ts        TEXT NOT NULL,
    event     TEXT NOT NULL,
    detail    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);
"""

SEED_KB = [
    ("IT", "Reset your password",
     ("Go to the SSO portal, click 'Forgot password', and follow the emailed "
     "link. Links expire after 30 minutes. If your account is locked after 5 "
     "failed attempts, contact IT support."),
     "password,sso,login,account"),
    ("IT", "Connect to the corporate VPN",
     ("Install the VPN client from the software center, then sign in with your "
     "SSO credentials and approve the MFA push on your phone. Split tunneling "
     "is enabled: only internal traffic routes through the VPN."),
     "vpn,network,remote,mfa"),
    ("IT", "Enroll in multi-factor authentication",
     ("Open the authenticator app, scan the QR code on the SSO security page, "
     "and enter the 6-digit code to verify. Keep backup codes in a safe place."),
     "mfa,2fa,security,authenticator"),
    ("IT", "Request a new laptop",
     ("File an equipment request in the IT portal with your manager's "
     "approval. Standard issue is a 14-inch laptop; engineering roles may "
     "request the high-performance option. Delivery takes 5 business days."),
     "laptop,hardware,equipment,onboarding"),
    ("IT", "Printer setup on macOS",
     ("Add the printer via System Settings > Printers using the print server "
     "address print.corp.local. Use your SSO username when prompted."),
     "printer,macos,printing"),
    ("IT", "Report a phishing email",
     ("Use the 'Report Phish' button in your mail client, then delete the "
     "message. Do not click links or open attachments. Security reviews "
     "reports within 4 hours."),
     "phishing,security,email,incident"),
    ("HR", "Annual leave policy",
     ("Full-time employees get 20 days of annual leave per year, accrued "
     "monthly. Requests over 5 consecutive days need manager approval two "
     "weeks in advance. Unused leave rolls over up to 5 days."),
     "leave,vacation,pto,time-off"),
    ("HR", "Payroll and payslips",
     ("Payday is the last business day of the month. Payslips are in the HR "
     "portal under Payroll > Documents. Payroll questions: payroll@corp.local."),
     "payroll,payslip,salary,payment"),
    ("HR", "Benefits enrollment",
     ("Open enrollment runs each November. New hires have 30 days from their "
     "start date to enroll. Changes outside these windows require a "
     "qualifying life event."),
     "benefits,insurance,enrollment,health"),
    ("HR", "Report workplace harassment",
     ("Reports can be made to your manager, HR business partner, or the "
     "anonymous ethics hotline. All reports are investigated confidentially "
     "within 10 business days."),
     "harassment,ethics,hotline,complaint"),
    ("HR", "Expense reports",
     ("Submit expenses in the finance portal within 30 days with itemized "
     "receipts. Per-diem for meals is $75/day domestic. Manager approval is "
     "required above $500."),
     "expenses,reimbursement,travel,per-diem"),
    ("HR", "New hire onboarding checklist",
     ("Day 1: collect laptop, complete I-9, enroll in benefits. Week 1: "
     "security training, team introductions. Your buddy is assigned by your "
     "manager."),
     "onboarding,new-hire,i-9,training"),
]

# SLA hours per priority
SLA_HOURS = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}

CATEGORIES = ("IT", "HR", "Facilities", "Security")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def db_path() -> Path:
    p = Path(settings.smartdesk_db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_conn(db: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db or db_path()))
    conn.row_factory = sqlite3.Row
    return conn


def seed() -> Path:
    path = db_path()
    if path.exists():
        path.unlink()
    conn = get_conn(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO kb_articles (category, title, body, tags)"
            " VALUES (?, ?, ?, ?)",
            SEED_KB,
        )
        conn.commit()
    finally:
        conn.close()
    return path


def ensure_seeded() -> Path:
    path = db_path()
    if not path.exists() or path.stat().st_size == 0:
        return seed()
    conn = get_conn(path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM kb_articles").fetchone()[0]
    except sqlite3.Error:
        conn.close()
        return seed()
    conn.close()
    return seed() if n == 0 else path


def log_event(ticket_id: int | None, event: str, detail: str = "") -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO audit_log (ticket_id, ts, event, detail)"
            " VALUES (?, ?, ?, ?)",
            (ticket_id, utcnow(), event, detail),
        )
        conn.commit()
    finally:
        conn.close()


def create_ticket(title: str, description: str, category: str,
                  priority: str, assignee: str = "unassigned") -> int:
    created = datetime.now(timezone.utc)
    sla_due = (created + timedelta(hours=SLA_HOURS[priority])).isoformat()
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO tickets (title, description, category, priority,"
            " status, assignee, created_at, sla_due)"
            " VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
            (title, description, category, priority, assignee,
             created.isoformat(), sla_due),
        )
        ticket_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    log_event(ticket_id, "created",
              f"category={category} priority={priority} assignee={assignee}")
    return ticket_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true")
    args = parser.parse_args()
    if args.seed:
        print(f"seeded {seed()}")
