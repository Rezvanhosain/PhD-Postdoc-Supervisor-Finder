"""OpenAlex /works client with abstract reconstruction.

This app requires OPENALEX_API_KEY for reliable batch use even though OpenAlex
offers basic keyless access. The key is passed via the ``api_key`` query param.
"""
from __future__ import annotations

from .http import HttpClient

BASE = "https://api.openalex.org"


def reconstruct_abstract(inverted_index: dict | None) -> str:
    """Rebuild plain-text abstract from OpenAlex ``abstract_inverted_index``."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda p: p[0])
    return " ".join(word for _, word in positions)


def _mailto(client: HttpClient) -> str:
    return client.contact if "@" in (client.contact or "") else ""


def search_works(client: HttpClient, query: str, api_key: str,
                 per_page: int = 25, from_year: int | None = 2015) -> list[dict]:
    """Search OpenAlex works for a query and return normalized evidence dicts."""
    filters = ["type:article"]
    if from_year:
        filters.append(f"from_publication_date:{from_year}-01-01")
    params = {
        "search": query,
        "per-page": max(1, min(per_page, 50)),
        "filter": ",".join(filters),
        "sort": "relevance_score:desc",
        "api_key": api_key,
    }
    mailto = _mailto(client)
    if mailto:
        params["mailto"] = mailto
    data = client.get_json(f"{BASE}/works", params)
    out: list[dict] = []
    for w in (data or {}).get("results", []):
        out.append(_normalize(w))
    return out


def _normalize(w: dict) -> dict:
    source = ((w.get("primary_location") or {}).get("source") or {})
    oa = w.get("open_access") or {}
    return {
        "title": w.get("display_name") or "",
        "authors": [au["author"]["display_name"]
                    for au in (w.get("authorships") or [])[:10]
                    if au.get("author")],
        "year": w.get("publication_year"),
        "venue": source.get("display_name") or "",
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "abstract": reconstruct_abstract(w.get("abstract_inverted_index")),
        "oa_url": oa.get("oa_url") or "",
        "cited_by": w.get("cited_by_count", 0),
        "source_api": "openalex",
        "source_ids": {"openalex": w.get("id", "")},
    }
