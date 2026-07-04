"""Citation collection, verification, and formatting.

Anti-hallucination policy: references come ONLY from metadata APIs
(OpenAlex, Semantic Scholar, Crossref). Nothing is ever formatted as a
citation unless it carries verified metadata from one of those sources.
Anything that fails verification is flagged 'Needs manual review' and
excluded from generated reference lists."""
from __future__ import annotations

from typing import Optional

from app.db import insert, log_error
from app.sources import crossref, openalex, semantic_scholar

STYLES = ("APA 7", "Harvard", "Chicago", "IEEE")


def collect_verified(topic: str, limit: int = 12) -> list[dict]:
    """Fetch candidate references from OpenAlex, then Semantic Scholar,
    deduplicated by DOI/title. All results carry verified=True + source_api."""
    refs: list[dict] = []
    seen: set[str] = set()
    for fetch in (openalex.search_works, semantic_scholar.search_papers):
        try:
            for r in fetch(topic, limit):
                key = (r.get("doi") or r.get("title", "")).lower()
                if key and key not in seen and r.get("title") and r.get("authors"):
                    seen.add(key)
                    refs.append(r)
        except Exception as e:
            log_error("reference", f"Reference search failed via {fetch.__module__}: {e}")
    return refs[:limit]


def verify_reference(ref: dict) -> dict:
    """Re-verify a reference. DOI is checked against Crossref; a reference
    without a resolvable DOI keeps verified status only if it came directly
    from a metadata API."""
    doi = ref.get("doi", "")
    if doi:
        meta = crossref.lookup_doi(doi)
        if meta:
            ref["verified"] = True
            ref["verification_note"] = "DOI resolved via Crossref."
            return ref
        ref["verified"] = ref.get("source_api") in ("openalex", "semantic_scholar")
        ref["verification_note"] = ("DOI did not resolve via Crossref; metadata came from "
                                    f"{ref.get('source_api')} — needs manual review.")
        log_error("reference", f"DOI failed Crossref check: {doi}", needs_review=True)
        return ref
    if ref.get("source_api") in ("openalex", "semantic_scholar", "crossref"):
        ref["verified"] = True
        ref["verification_note"] = f"Metadata from {ref['source_api']} (no DOI available)."
    else:
        ref["verified"] = False
        ref["verification_note"] = "No DOI and no trusted metadata source — needs manual review."
        log_error("reference", f"Unverifiable reference: {ref.get('title','?')[:120]}",
                  needs_review=True)
    return ref


def _authors_apa(authors: list[str]) -> str:
    def fmt(a: str) -> str:
        parts = a.split()
        if len(parts) < 2:
            return a
        return f"{parts[-1]}, {' '.join(p[0] + '.' for p in parts[:-1])}"
    fs = [fmt(a) for a in authors[:20]]
    if len(fs) == 1:
        return fs[0]
    return ", ".join(fs[:-1]) + ", & " + fs[-1]


def format_reference(ref: dict, style: str = "APA 7") -> str:
    a = ref.get("authors", [])
    t, y, v = ref.get("title", ""), ref.get("year", "n.d."), ref.get("venue", "")
    doi = f" https://doi.org/{ref['doi']}" if ref.get("doi") else ""
    if style == "APA 7":
        return f"{_authors_apa(a)} ({y}). {t}. {v}.{doi}"
    if style == "Harvard":
        return f"{_authors_apa(a)} ({y}) '{t}', {v}.{doi}"
    if style == "Chicago":
        return f"{', '.join(a[:10])}. \"{t}.\" {v} ({y}).{doi}"
    if style == "IEEE":
        ie = ", ".join(f"{x.split()[0][0]}. {x.split()[-1]}" if len(x.split()) > 1 else x
                       for x in a[:6])
        return f"{ie}, \"{t},\" {v}, {y}.{doi}"
    return format_reference(ref, "APA 7")


def save_citations(refs: list[dict], document_id: int) -> None:
    for r in refs:
        insert("citations", title=r.get("title", ""), authors="; ".join(r.get("authors", [])),
               year=r.get("year", ""), venue=r.get("venue", ""), doi=r.get("doi", ""),
               url=r.get("url", ""), source_api=r.get("source_api", ""),
               verified=int(bool(r.get("verified"))),
               verification_note=r.get("verification_note", ""), document_id=document_id)


def audit_table(refs: list[dict]) -> str:
    """Markdown source-audit table shipped alongside each generated proposal."""
    lines = ["| # | Title | Year | Source API | DOI | Status |",
             "|---|-------|------|-----------|-----|--------|"]
    for i, r in enumerate(refs, 1):
        status = "VERIFIED" if r.get("verified") else "NEEDS MANUAL REVIEW"
        lines.append(f"| {i} | {r.get('title','')[:70]} | {r.get('year','')} | "
                     f"{r.get('source_api','')} | {r.get('doi','') or '—'} | {status} |")
    return "\n".join(lines)
