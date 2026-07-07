"""ORCID public API (https://pub.orcid.org) — free, no key required.

Used as a *structured identity source*: an ORCID iD whose record names the
same institution is strong evidence that a supervisor candidate is a real,
currently-affiliated person. Public emails on the record are taken verbatim
(confidence 'orcid_public'); nothing is guessed here."""
from __future__ import annotations

from app.sources.http import get_json

BASE = "https://pub.orcid.org/v3.0"
_H = {"Accept": "application/json"}


def search_person(name: str, institution: str = "") -> dict | None:
    """Find the best ORCID match for name (+ institution). Returns
    {orcid, name, institution, email} or None if no confident match."""
    q = f'given-and-family-names:"{name}"'
    if institution:
        q += f' AND affiliation-org-name:"{institution}"'
    data = get_json(f"{BASE}/expanded-search/?q={q}&rows=5", headers=_H)
    hits = (data or {}).get("expanded-result") or []
    if not hits and institution:  # retry without affiliation constraint
        data = get_json(f"{BASE}/expanded-search/?q=given-and-family-names:\"{name}\"&rows=5",
                        headers=_H)
        hits = (data or {}).get("expanded-result") or []
    name_l = name.lower()
    inst_l = institution.lower()
    for h in hits:
        full = f"{h.get('given-names','')} {h.get('family-names','')}".strip()
        if full.lower() != name_l:
            continue
        orgs = [o for o in (h.get("institution-name") or []) if o]
        # require institutional corroboration when we know the institution
        org_ok = (not institution) or any(
            _org_overlap(o, inst_l) for o in orgs)
        if not org_ok:
            continue
        emails = h.get("email") or []
        return {"orcid": h.get("orcid-id", ""), "name": full,
                "institutions": orgs,
                "email": emails[0] if emails else ""}
    return None


def _org_overlap(org: str, inst_l: str) -> bool:
    stop = {"university", "universität", "universiteit", "the", "and"}
    a = {w for w in org.lower().split() if len(w) > 3 and w not in stop}
    b = {w for w in inst_l.split() if len(w) > 3 and w not in stop}
    return bool(a & b)
