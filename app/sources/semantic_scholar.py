"""Semantic Scholar Graph API — free tier works without a key (rate limited);
an API key can be added in Settings for higher limits."""
from __future__ import annotations

from typing import Optional

from app.config import get_setting
from app.sources.http import get_json

BASE = "https://api.semanticscholar.org/graph/v1"


def _headers() -> Optional[dict]:
    key = get_setting("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": key} if key else None


def search_authors(query: str, limit: int = 20) -> list[dict]:
    data = get_json(f"{BASE}/author/search", {
        "query": query, "limit": limit,
        "fields": "name,affiliations,homepage,paperCount,citationCount,hIndex,url",
    }, headers=_headers())
    if not data:
        return []
    out = []
    for a in data.get("data", []):
        out.append({
            "name": a.get("name", ""),
            "university": "; ".join(a.get("affiliations") or []),
            "department": "",
            "country": "",
            "email": "",
            "email_confidence": "unknown",
            "profile_url": a.get("url", "") or a.get("homepage", "") or "",
            "research_areas": [],
            "publications": [],
            "metrics": {
                "works_count": a.get("paperCount"),
                "cited_by_count": a.get("citationCount"),
                "h_index": a.get("hIndex"),
            },
            "supervises_phd": "unknown",
            "source": "semantic_scholar",
            "source_url": a.get("url", ""),
            "external_id": f"s2:{a.get('authorId')}",
        })
    return out


def search_papers(query: str, limit: int = 10) -> list[dict]:
    data = get_json(f"{BASE}/paper/search", {
        "query": query, "limit": limit,
        "fields": "title,year,venue,externalIds,authors,url,citationCount",
    }, headers=_headers())
    if not data:
        return []
    out = []
    for p in data.get("data", []):
        doi = (p.get("externalIds") or {}).get("DOI", "")
        out.append({
            "title": p.get("title", ""),
            "year": str(p.get("year") or ""),
            "venue": p.get("venue", ""),
            "doi": doi,
            "url": p.get("url", ""),
            "authors": [a["name"] for a in (p.get("authors") or [])[:6]],
            "cited_by": p.get("citationCount", 0),
            "source_api": "semantic_scholar",
            "verified": True,
        })
    return out
