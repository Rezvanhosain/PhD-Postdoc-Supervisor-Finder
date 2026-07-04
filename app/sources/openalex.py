"""OpenAlex API (https://openalex.org) — free, no key required.
Used for supervisor discovery and citation verification."""
from __future__ import annotations

from typing import Optional

from app.db import insert, now
from app.sources.http import get_json

BASE = "https://api.openalex.org"


def search_authors(query: str, country: Optional[str] = None,
                   per_page: int = 25) -> list[dict]:
    """Search authors by name; if that finds nothing (topic queries), discover
    authors through recent works on the topic instead."""
    params: dict = {"search": query, "per-page": per_page}
    filters = ["works_count:>5"]
    if country:
        filters.append(f"last_known_institutions.country_code:{country.upper()}")
    params["filter"] = ",".join(filters)
    data = get_json(f"{BASE}/authors", params)
    results = (data or {}).get("results", [])
    if not results:
        results = _authors_from_works(query, country, per_page)
    out = []
    for a in results:
        inst = (a.get("last_known_institutions") or [{}])
        inst = inst[0] if inst else {}
        topics = [t["display_name"] for t in (a.get("topics") or [])[:8]]
        out.append({
            "name": a.get("display_name", ""),
            "university": inst.get("display_name", ""),
            "department": "",
            "country": inst.get("country_code", "") or "",
            "email": "",
            "email_confidence": "unknown",
            "profile_url": a.get("id", ""),
            "research_areas": topics,
            "publications": [],
            "metrics": {
                "works_count": a.get("works_count"),
                "cited_by_count": a.get("cited_by_count"),
                "h_index": (a.get("summary_stats") or {}).get("h_index"),
            },
            "supervises_phd": "unknown",
            "source": "openalex",
            "source_url": a.get("id", ""),
            "external_id": a.get("id", ""),
        })
    return out


def _authors_from_works(query: str, country: Optional[str], limit: int) -> list[dict]:
    """Topic route: search recent works, collect their (first/last) authors,
    then fetch full author records."""
    data = get_json(f"{BASE}/works", {
        "search": query, "per-page": 25,
        "filter": "type:article,from_publication_date:2019-01-01",
        "sort": "relevance_score:desc"})
    ids: list[str] = []
    for w in (data or {}).get("results", []):
        for au in (w.get("authorships") or []):
            aid = (au.get("author") or {}).get("id")
            if aid and aid not in ids:
                ids.append(aid)
    if not ids:
        return []
    short = "|".join(a.rstrip("/").split("/")[-1] for a in ids[:40])
    filters = [f"ids.openalex:{short}", "works_count:>5"]
    if country:
        filters.append(f"last_known_institutions.country_code:{country.upper()}")
    data = get_json(f"{BASE}/authors", {"filter": ",".join(filters), "per-page": limit})
    return (data or {}).get("results", [])


def author_recent_works(author_id: str, limit: int = 8) -> list[dict]:
    """Recent works for an OpenAlex author URL/ID. Verified metadata only."""
    aid = author_id.rstrip("/").split("/")[-1]
    data = get_json(f"{BASE}/works", {
        "filter": f"authorships.author.id:{aid}",
        "sort": "publication_date:desc", "per-page": limit,
    })
    if not data:
        return []
    works = []
    for w in data.get("results", []):
        works.append({
            "title": w.get("display_name", ""),
            "year": str(w.get("publication_year", "")),
            "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
            "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
            "url": w.get("id", ""),
            "authors": [au["author"]["display_name"] for au in (w.get("authorships") or [])[:6]],
            "source_api": "openalex",
            "verified": True,
        })
    return works


def search_works(query: str, limit: int = 10) -> list[dict]:
    """Topic search for literature — used for verified proposal references."""
    data = get_json(f"{BASE}/works", {
        "search": query, "per-page": limit,
        "filter": "type:article", "sort": "relevance_score:desc",
    })
    if not data:
        return []
    out = []
    for w in data.get("results", []):
        out.append({
            "title": w.get("display_name", ""),
            "year": str(w.get("publication_year", "")),
            "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name", ""),
            "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
            "url": w.get("id", ""),
            "authors": [au["author"]["display_name"] for au in (w.get("authorships") or [])[:6]],
            "cited_by": w.get("cited_by_count", 0),
            "source_api": "openalex",
            "verified": True,
        })
    return out


def save_supervisor(s: dict) -> int:
    import json as _json

    return insert(
        "supervisors",
        name=s["name"], university=s["university"], department=s.get("department", ""),
        country=s.get("country", ""), email=s.get("email", ""),
        email_confidence=s.get("email_confidence", "unknown"),
        profile_url=s.get("profile_url", ""),
        research_areas=_json.dumps(s.get("research_areas", [])),
        publications=_json.dumps(s.get("publications", [])),
        metrics=_json.dumps(s.get("metrics", {})),
        supervises_phd=s.get("supervises_phd", "unknown"),
        source=s.get("source", ""), source_url=s.get("source_url", ""),
        date_accessed=now(), external_id=s.get("external_id") or s.get("source_url"),
    )
