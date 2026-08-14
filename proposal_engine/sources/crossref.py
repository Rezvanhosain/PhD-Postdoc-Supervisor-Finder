"""Crossref REST client — DOI verification for the citation audit."""
from __future__ import annotations

from .http import HttpClient, SourceError

BASE = "https://api.crossref.org"


def lookup_doi(client: HttpClient, doi: str) -> dict | None:
    """Return verified metadata for a DOI, or None if it does not resolve."""
    doi = (doi or "").strip().replace("https://doi.org/", "")
    if not doi:
        return None
    try:
        data = client.get_json(f"{BASE}/works/{doi}")
    except SourceError:
        return None
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
        "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip()
                    for a in (m.get("author") or [])[:10]],
        "source_api": "crossref",
    }
