"""Stage 5 — Bibliography and basic citation audit.

The bibliography is built ONLY from evidence_store entries actually cited in
proposal_draft.md. The LLM never creates bibliography text. References are
emitted as CSL-JSON; each cited entry is audited (DOI resolution + metadata
agreement) and the result written to citation_audit.csv.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from rapidfuzz import fuzz

from .validators import extract_citation_keys

VERIFIED = "verified"
METADATA_MISMATCH = "metadata_mismatch"
DOI_UNRESOLVED = "doi_unresolved"
NO_DOI = "no_doi"


class CitationGateError(RuntimeError):
    """Raised when in-text citation keys are missing from the evidence store."""


def cited_keys_in(draft_md: str) -> list[str]:
    return extract_citation_keys(draft_md)


def _split_name(name: str) -> dict:
    parts = name.split()
    if len(parts) < 2:
        return {"family": name, "given": ""}
    return {"family": parts[-1], "given": " ".join(parts[:-1])}


def to_csl(entry: dict) -> dict:
    csl = {
        "id": entry["key"],
        "type": "article-journal",
        "title": entry.get("title", ""),
        "author": [_split_name(a) for a in entry.get("authors", []) if a],
        "container-title": entry.get("venue", ""),
    }
    year = entry.get("year")
    if year:
        try:
            csl["issued"] = {"date-parts": [[int(year)]]}
        except (ValueError, TypeError):
            csl["issued"] = {"literal": str(year)}
    if entry.get("doi"):
        csl["DOI"] = entry["doi"]
        csl["URL"] = f"https://doi.org/{entry['doi']}"
    elif entry.get("oa_url"):
        csl["URL"] = entry["oa_url"]
    return csl


def build_bibliography(draft_md: str, evidence: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (cited_entries, csl_items) for entries actually cited in the draft.

    Raises CitationGateError if any in-text key is absent from the evidence store.
    """
    by_key = {e["key"]: e for e in evidence}
    cited = cited_keys_in(draft_md)
    missing = [k for k in cited if k not in by_key]
    if missing:
        raise CitationGateError(f"in-text citation keys missing from evidence_store: {missing}")
    cited_entries = [by_key[k] for k in cited]
    csl_items = [to_csl(e) for e in cited_entries]
    return cited_entries, csl_items


def _metadata_agrees(entry: dict, meta: dict) -> bool:
    title_score = fuzz.token_sort_ratio(entry.get("title", ""), meta.get("title", ""))
    if title_score < 80:
        return False
    y1, y2 = str(entry.get("year") or ""), str(meta.get("year") or "")
    if y1 and y2 and y1 != y2:
        return False
    return True


def audit_citations(cited_entries: list[dict], verify_doi) -> list[dict]:
    """Audit each cited entry. ``verify_doi(doi) -> metadata dict | None``."""
    rows: list[dict] = []
    for e in cited_entries:
        doi = (e.get("doi") or "").strip()
        if not doi:
            status, note = NO_DOI, "No DOI in metadata; source API record only."
        else:
            meta = None
            try:
                meta = verify_doi(doi)
            except Exception as ex:  # verifier failure is surfaced, not swallowed
                note = f"DOI verification error: {ex}"
                meta = None
            if meta is None:
                status, note = DOI_UNRESOLVED, "DOI did not resolve via Crossref."
            elif _metadata_agrees(e, meta):
                status, note = VERIFIED, "DOI resolved; metadata agrees with evidence store."
            else:
                status, note = METADATA_MISMATCH, "DOI resolved but title/year disagree."
        rows.append({
            "key": e["key"], "title": e.get("title", ""), "year": e.get("year", ""),
            "doi": doi, "source_api": e.get("source_api", ""), "status": status,
            "needs_human_review": status != VERIFIED, "note": note,
        })
    return rows


def write_references_json(csl_items: list[dict], out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(csl_items, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def write_audit_csv(rows: list[dict], out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["key", "title", "year", "doi", "source_api", "status",
                    "needs_human_review", "note"])
        for r in rows:
            w.writerow([r["key"], r["title"], r["year"], r["doi"], r["source_api"],
                        r["status"], r["needs_human_review"], r["note"]])
    return out
