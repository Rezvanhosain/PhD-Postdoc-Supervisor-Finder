"""Stage 3 — Evidence Build.

Collects works from OpenAlex (primary) and Semantic Scholar (fallback),
deduplicates by DOI then fuzzy title, attaches a relevance note, and enforces
the ``evidence_minimum`` gate (broadening the search once if needed).

The source layer is injected via an ``EvidenceProvider`` so tests can supply
recorded fixtures with no network access.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from rapidfuzz import fuzz

from .config import EngineConfig
from .sources import HttpClient
from .sources import openalex as oa
from .sources import semantic_scholar as s2
from .sources import unpaywall as up

TITLE_MATCH_THRESHOLD = 90  # rapidfuzz token_sort_ratio
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class InsufficientEvidence(RuntimeError):
    def __init__(self, found: int, needed: int):
        self.found = found
        self.needed = needed
        super().__init__(f"insufficient evidence: {found} papers with abstracts < {needed}")


# --------------------------------------------------------------------- providers
class EvidenceProvider:
    """Interface: return a list of normalized work dicts for a query."""

    def works(self, query: str, per_page: int) -> list[dict]:  # pragma: no cover
        raise NotImplementedError


class LiveProvider(EvidenceProvider):
    def __init__(self, client: HttpClient, openalex_key: str,
                 s2_key: str | None = None, unpaywall_email: str | None = None):
        self.client = client
        self.openalex_key = openalex_key
        self.s2_key = s2_key
        self.unpaywall_email = unpaywall_email

    def works(self, query: str, per_page: int) -> list[dict]:
        results = oa.search_works(self.client, query, self.openalex_key, per_page=per_page)
        results += s2.search_papers(self.client, query, self.s2_key, limit=per_page)
        if self.unpaywall_email:
            for r in results:
                if not r.get("oa_url") and r.get("doi"):
                    r["oa_url"] = up.oa_url(self.client, r["doi"], self.unpaywall_email)
        return results


# --------------------------------------------------------------------- helpers
def _citation_key(entry: dict, taken: set[str]) -> str:
    authors = entry.get("authors") or []
    last = ""
    if authors:
        last = authors[0].split()[-1] if authors[0].split() else authors[0]
    last = re.sub(r"[^A-Za-z]", "", last).lower() or "anon"
    year = str(entry.get("year") or "nd")
    base = f"{last}{year}"
    key = base
    suffix = ord("a")
    while key in taken:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    taken.add(key)
    return key


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if len(w) > 2}


def deterministic_relevance(entry: dict, query_terms: set[str]) -> str:
    title_hits = query_terms & _tokens(entry.get("title", ""))
    abs_hits = (query_terms & _tokens(entry.get("abstract", ""))) - title_hits
    bits = []
    if title_hits:
        bits.append("title matches " + ", ".join(sorted(title_hits)))
    if abs_hits:
        bits.append("abstract mentions " + ", ".join(sorted(abs_hits)))
    if not bits:
        bits.append("topically retrieved by the search query")
    cited = entry.get("cited_by")
    tail = f"; cited {cited} times" if cited else ""
    return "Relevant because " + "; ".join(bits) + tail + "."


def dedupe(entries: list[dict]) -> list[dict]:
    """De-duplicate by DOI, then fuzzy title match. Prefer entries with abstracts."""
    kept: list[dict] = []
    seen_doi: dict[str, int] = {}
    for e in entries:
        doi = (e.get("doi") or "").lower().strip()
        if doi and doi in seen_doi:
            _merge_into(kept[seen_doi[doi]], e)
            continue
        match_idx = None
        if not doi:
            for i, k in enumerate(kept):
                if fuzz.token_sort_ratio(e.get("title", ""), k.get("title", "")) >= TITLE_MATCH_THRESHOLD:
                    match_idx = i
                    break
        if match_idx is not None:
            _merge_into(kept[match_idx], e)
            continue
        kept.append(dict(e))
        if doi:
            seen_doi[doi] = len(kept) - 1
    return kept


def _merge_into(base: dict, other: dict) -> None:
    """Enrich an existing entry with fields from a duplicate."""
    if not base.get("abstract") and other.get("abstract"):
        base["abstract"] = other["abstract"]
    if not base.get("oa_url") and other.get("oa_url"):
        base["oa_url"] = other["oa_url"]
    if not base.get("doi") and other.get("doi"):
        base["doi"] = other["doi"]
    ids = dict(base.get("source_ids") or {})
    ids.update(other.get("source_ids") or {})
    base["source_ids"] = ids


def build_evidence(provider: EvidenceProvider, queries: list[str], config: EngineConfig,
                   broaden_query: str | None = None) -> list[dict]:
    """Run the queries, dedupe, keep entries with abstracts, assign keys + notes."""
    query_terms: set[str] = set()
    for q in queries:
        query_terms |= _tokens(q)

    raw: list[dict] = []
    for q in queries:
        raw += provider.works(q, config.per_query_results)

    deduped = dedupe(raw)
    with_abstract = [e for e in deduped if (e.get("abstract") or "").strip()]

    if len(with_abstract) < config.evidence_minimum and broaden_query:
        raw += provider.works(broaden_query, config.per_query_results)
        deduped = dedupe(raw)
        with_abstract = [e for e in deduped if (e.get("abstract") or "").strip()]

    taken: set[str] = set()
    for e in with_abstract:
        e["key"] = _citation_key(e, taken)
        e["relevance_note"] = deterministic_relevance(e, query_terms)
        e.setdefault("oa_url", "")
    return with_abstract


def enforce_minimum(entries: list[dict], config: EngineConfig) -> None:
    if len(entries) < config.evidence_minimum:
        raise InsufficientEvidence(len(entries), config.evidence_minimum)


# --------------------------------------------------------------------- output
def write_evidence_store(entries: list[dict], out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def write_evidence_table(entries: list[dict], out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "title", "authors", "year", "venue", "doi", "oa_url",
                    "source_api", "relevance_note"])
        for e in entries:
            w.writerow([
                e.get("key", ""), e.get("title", ""), "; ".join(e.get("authors", [])),
                e.get("year", ""), e.get("venue", ""), e.get("doi", ""),
                e.get("oa_url", ""), e.get("source_api", ""), e.get("relevance_note", ""),
            ])
    return out
