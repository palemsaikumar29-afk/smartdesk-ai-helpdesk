from src.agents.nodes import keyword_triage
from src.services import kb


def test_triage_it_password():
    d = keyword_triage("Forgot password", "I cannot login to the SSO portal")
    assert d.category == "IT"
    assert d.priority in ("P1", "P2", "P3")


def test_triage_hr_leave():
    d = keyword_triage("Annual leave request", "I want 10 days vacation in December")
    assert d.category == "HR"


def test_triage_security_p1():
    d = keyword_triage("Possible breach", "We suspect a ransomware infection, urgent")
    assert d.category == "Security"
    assert d.priority == "P1"


def test_triage_facilities():
    d = keyword_triage("Badge not working", "My office badge won't open the parking gate")
    assert d.category == "Facilities"


def test_triage_outage_p1():
    d = keyword_triage("VPN outage", "VPN is down for the whole team, production blocked")
    assert d.priority == "P1"


def test_triage_default_p3():
    d = keyword_triage("Question", "Just a general question about the office")
    assert d.priority == "P3"
    assert 0.0 <= d.confidence <= 1.0


def test_kb_search_password():
    hits = kb.search_kb("how do I reset my password")
    assert hits and hits[0]["title"] == "Reset your password"


def test_kb_search_category_filter():
    hits = kb.search_kb("password", category="HR")
    assert hits == []


def test_kb_search_vpn():
    hits = kb.search_kb("vpn client install mfa")
    assert hits and any("VPN" in h["title"] for h in hits)


def test_kb_search_no_match():
    assert kb.search_kb("quantum banana spaceship") == []


def test_kb_seed_count():
    from src.database import db as dbmod

    conn = dbmod.get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM kb_articles").fetchone()[0] == 13
    finally:
        conn.close()


def test_kb_search_wfh_returns_wfh_article():
    hits = kb.search_kb("What is the company's work from home policy?",
                        category="HR")
    assert hits and hits[0]["title"] == "Work from home policy"
    assert hits[0]["category"] == "HR"


def test_kb_search_offtopic_returns_no_match_signal():
    # A lone common word ("policy") must not drag in unrelated HR policy
    # articles: this query returned "Annual leave policy" before the
    # relevance floor was added.
    assert kb.search_kb("What is the policy regarding office parking "
                        "for visitors?", category="HR") == []


def test_kb_search_vpn_control():
    hits = kb.search_kb("vpn")
    assert hits and "VPN" in hits[0]["title"]
