"""Unpaywall client — optional open-access URL enrichment."""
from __future__ import annotations

from .http import HttpClient, SourceError

BASE = "https://api.unpaywall.org/v2"


def oa_url(client: HttpClient, doi: str, email: str) -> str:
    """Best open-access URL for a DOI, or '' if none / unavailable."""
    doi = (doi or "").strip().replace("https://doi.org/", "")
    if not doi or not email:
        return ""
    try:
        data = client.get_json(f"{BASE}/{doi}", {"email": email})
    except SourceError:
        return ""
    if not data:
        return ""
    best = data.get("best_oa_location") or {}
    return best.get("url") or best.get("url_for_pdf") or ""
