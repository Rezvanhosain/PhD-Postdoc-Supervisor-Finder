"""Semantic Scholar Graph API (api.semanticscholar.org) — free tier, no key.

Second bibliometric identity source: corroborates a candidate found via
OpenAlex/official pages, and acts as a fallback discovery route when
OpenAlex returns nothing for an institution+topic pair."""
from __future__ import annotations

from app.sources.http import get_json

BASE = "https://api.semanticscholar.org/graph/v1"
_FIELDS = "name,affiliations,url,paperCount,hIndex,homepage"


def find_author(name: str, institution: str = "") -> dict | None:
    """Best exact-name author match, preferring institution overlap."""
    data = get_json(f"{BASE}/author/search",
                    {"query": name, "fields": _FIELDS, "limit": 10})
    hits = (data or {}).get("data") or []
    name_l = name.lower()
    inst_words = {w for w in institution.lower().split() if len(w) > 3
                  and w not in ("university", "universität")}
    exact = [h for h in hits if (h.get("name") or "").lower() == name_l]
    for h in exact:
        affs = " ".join(h.get("affiliations") or []).lower()
        if not inst_words or any(w in affs for w in inst_words):
            return _shape(h)
    # exact name but no affiliation data on S2 — still a weak corroboration
    if len(exact) == 1:
        return _shape(exact[0])
    return None


def _shape(h: dict) -> dict:
    return {"s2_id": h.get("authorId", ""), "name": h.get("name", ""),
            "url": h.get("url", ""), "paper_count": h.get("paperCount"),
            "h_index": h.get("hIndex"),
            "affiliations": h.get("affiliations") or [],
            "homepage": h.get("homepage") or ""}
