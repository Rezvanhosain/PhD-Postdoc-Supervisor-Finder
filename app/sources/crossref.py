"""Crossref REST API — DOI verification for citations."""
from __future__ import annotations

from typing import Optional

from app.sources.http import get_json

BASE = "https://api.crossref.org"


def lookup_doi(doi: str) -> Optional[dict]:
    """Return verified metadata for a DOI, or None if it does not resolve."""
    doi = doi.strip().replace("https://doi.org/", "")
    if not doi:
        return None
    data = get_json(f"{BASE}/works/{doi}")
    if not data or "message" not in data:
        return None
    m = data["message"]
    year = ""
    for k in ("published-print", "published-online", "issued"):
        parts = (m.get(k) or {}).get("date-parts")
        if parts and parts[0]:
            year = str(parts[0][0])
            break
    return {
        "title": (m.get("title") or [""])[0],
        "year": year,
        "venue": (m.get("container-title") or [""])[0],
        "doi": m.get("DOI", doi),
        "url": m.get("URL", f"https://doi.org/{doi}"),
        "authors": [f"{a.get('given','')} {a.get('family','')}".strip()
                    for a in (m.get("author") or [])[:10]],
        "source_api": "crossref",
        "verified": True,
    }
