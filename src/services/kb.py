"""Knowledge-base search: token-overlap scoring over seeded articles."""
from __future__ import annotations

import re

from ..database.db import get_conn

_WORD = re.compile(r"[a-z]{3,}")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def search_kb(query: str, category: str | None = None,
              limit: int = 3) -> list[dict]:
    qtokens = _tokens(query)
    conn = get_conn()
    try:
        if category:
            rows = conn.execute(
                "SELECT article_id, category, title, body, tags FROM kb_articles"
                " WHERE category = ?",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT article_id, category, title, body, tags FROM kb_articles"
            ).fetchall()
    finally:
        conn.close()
    scored = []
    for r in rows:
        hay = f"{r['title']} {r['body']} {r['tags']}"
        htokens = _tokens(hay)
        overlap = qtokens & htokens
        # title hits weigh double
        title_hits = len(qtokens & _tokens(r["title"]))
        score = len(overlap) + title_hits
        if score:
            scored.append((score, dict(r)))
    scored.sort(key=lambda s: -s[0])
    return [{"article_id": r["article_id"], "category": r["category"],
             "title": r["title"], "body": r["body"], "score": s}
            for s, r in scored[:limit]]
