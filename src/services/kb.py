"""Knowledge-base search: token-overlap scoring over seeded articles.

A candidate article only counts as a match when its token overlap with the
query clears a relevance floor; otherwise search_kb returns [] - the explicit
"no relevant article found" signal - instead of unrelated fallback articles.
"""
from __future__ import annotations

import math
import re

from ..database.db import get_conn

_WORD = re.compile(r"[a-z]{3,}")

# Common function words carry no retrieval signal ("the", "what", ...).
# Filtered from the query side only; a haystack word can never match a
# query token that is not there.
STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "what", "how", "why", "when",
    "where", "are", "you", "your", "yours", "our", "ours", "their",
    "theirs", "this", "that", "these", "those", "was", "were", "been",
    "has", "have", "had", "will", "would", "could", "should", "about",
    "into", "over", "after", "before", "between", "during", "under",
    "than", "then", "also", "such", "per", "via",
})


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def min_overlap(n_query_tokens: int) -> int:
    """Relevance floor: minimum query-token overlap for a match.

    At least one matched content token is always required, and longer
    queries must match proportionally more tokens (a quarter, rounded up).
    This keeps exact short queries like 'vpn' working while stopping a
    single common word such as 'policy' from dragging in unrelated
    articles.
    """
    return max(1, math.ceil(n_query_tokens / 4))


def search_kb(query: str, category: str | None = None,
              limit: int = 3) -> list[dict]:
    qtokens = _tokens(query) - STOPWORDS
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
    floor = min_overlap(len(qtokens))
    scored = []
    for r in rows:
        hay = f"{r['title']} {r['body']} {r['tags']}"
        htokens = _tokens(hay)
        overlap = qtokens & htokens
        if len(overlap) < floor:
            continue  # below the relevance floor: not a real match
        # title hits weigh double
        title_hits = len(qtokens & _tokens(r["title"]))
        score = len(overlap) + title_hits
        scored.append((score, dict(r)))
    scored.sort(key=lambda s: -s[0])
    return [{"article_id": r["article_id"], "category": r["category"],
             "title": r["title"], "body": r["body"], "score": s}
            for s, r in scored[:limit]]
