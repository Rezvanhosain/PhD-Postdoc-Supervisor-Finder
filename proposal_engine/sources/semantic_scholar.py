"""Semantic Scholar Graph API client — fallback / enrichment source."""
from __future__ import annotations

from .http import HttpClient, SourceError

BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "title,abstract,year,venue,externalIds,authors,openAccessPdf,citationCount"


def search_papers(client: HttpClient, query: str, api_key: str | None = None,
                  limit: int = 25) -> list[dict]:
    params = {"query": query, "limit": max(1, min(limit, 100)), "fields": FIELDS}
    headers = {"x-api-key": api_key} if api_key else None
    try:
        data = client.get_json(f"{BASE}/paper/search", params, headers=headers)
    except SourceError:
        # S2 is a soft dependency; a failure here must not abort the run.
        return []
    out: list[dict] = []
    for p in (data or {}).get("data", []):
        ext = p.get("externalIds") or {}
        out.append({
            "title": p.get("title") or "",
            "authors": [a.get("name", "") for a in (p.get("authors") or [])[:10] if a.get("name")],
            "year": p.get("year"),
            "venue": p.get("venue") or "",
            "doi": (ext.get("DOI") or "").replace("https://doi.org/", ""),
            "abstract": p.get("abstract") or "",
            "oa_url": (p.get("openAccessPdf") or {}).get("url") or "",
            "cited_by": p.get("citationCount", 0),
            "source_api": "semantic_scholar",
            "source_ids": {k: v for k, v in ext.items()},
        })
    return out
