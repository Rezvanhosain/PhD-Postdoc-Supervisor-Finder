"""Multi-source identity enrichment + contact readiness (workflow step 4b).

For each *already-vetted* supervisor this tries, in order of trust:
  1. ORCID (structured identity, sometimes a public email)
  2. Semantic Scholar (bibliometric corroboration, sometimes a homepage)
  3. The person's official profile page (title, public email)
  4. Institutional email pattern — GUESS, only when identity evidence is
     strong and the institution's mail domain is confirmed from real
     addresses seen on the official site; always marked 'pattern_guess'
     and never treated as a verified address by the outreach gate.

Nothing here can create a supervisor; it only strengthens (or fails to
strengthen) records that already passed vetting. All evidence is appended
to metrics['evidence'] and a contact-readiness score is stored."""
from __future__ import annotations

import json
import re

from app.db import execute, rows
from app.sources import orcid, semanticscholar
from app.sources.http import get
from app.vetting import contact_readiness

_EMAIL_RX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_TITLE_RX = re.compile(
    r"\b(Professor|Prof\.|Associate Professor|Assistant Professor|"
    r"University Lecturer|Senior Researcher|Research Director|Docent|"
    r"Juniorprofessor|Privatdozent)\b", re.I)

# mail domains confirmed by addresses actually observed on official pages;
# {institution-lowercase-key: domain}
_KNOWN_MAIL_DOMAINS = {"tampere": "tuni.fi"}


def enrich_supervisor(supervisor_id: int) -> dict:
    """Run all enrichment sources for one stored supervisor. Returns a
    summary of what was added; updates the DB row in place."""
    got = rows("SELECT * FROM supervisors WHERE id=?", (supervisor_id,))
    if not got:
        return {"error": "not found"}
    s = got[0]
    metrics = json.loads(s.get("metrics") or "{}")
    evidence: list[str] = list(metrics.get("evidence") or [])
    added: list[str] = []
    email = (s.get("email") or "").strip()
    email_conf = s.get("email_confidence") or "unknown"
    title = s.get("title") or ""

    # 1. ORCID — re-run when the affiliation cross-check hasn't happened yet
    # (records enriched before that check existed have orcid but no verdict)
    if not metrics.get("orcid") or "orcid_affiliations" not in metrics:
        hit = orcid.search_person(s["name"], s.get("university", ""))
        if hit:
            metrics["orcid"] = hit["orcid"]
            metrics["orcid_affiliations"] = hit.get("institutions") or []
            ev = (f"ORCID {hit['orcid']} names affiliation(s) "
                  f"{', '.join(hit['institutions'][:2]) or '(none listed)'}")
            evidence.append(ev); added.append("orcid")
            # ORCID naming only OTHER institutions is strong evidence the
            # person moved or this is a same-name collision — record it so
            # the outreach gate forces manual review instead of drafting an
            # email to the wrong institution's address.
            from app.vetting import institution_match
            insts = hit.get("institutions") or []
            if insts and not any(institution_match(i, s.get("university", ""))
                                 for i in insts):
                metrics["orcid_affiliation_mismatch"] = insts
                evidence.append(
                    f"WARNING: ORCID affiliation(s) ({', '.join(insts[:2])}) do NOT "
                    f"match {s.get('university','the opportunity institution')} — "
                    "possible institutional move or same-name collision")
            if hit.get("email") and not email:
                email, email_conf = hit["email"], "orcid_public"
                evidence.append(f"Public email on ORCID record: {email}")
                added.append("email:orcid")

    # 2. Semantic Scholar
    if not metrics.get("s2_id"):
        hit = semanticscholar.find_author(s["name"], s.get("university", ""))
        if hit:
            metrics["s2_id"] = hit["s2_id"]
            metrics.setdefault("s2_paper_count", hit.get("paper_count"))
            evidence.append(
                f"Semantic Scholar author {hit['s2_id']} "
                f"({hit.get('paper_count')} papers, h={hit.get('h_index')})")
            added.append("semantic_scholar")
            if hit.get("homepage") and not s.get("profile_url"):
                execute("UPDATE supervisors SET profile_url=? WHERE id=?",
                        (hit["homepage"], supervisor_id))

    # 3. Official profile page: title + public email near the surname
    purl = s.get("profile_url") or ""
    if purl.startswith("http") and "openalex.org" not in purl and \
            (not email or not title):
        html = get(purl, check_robots=True)
        if html:
            surname = s["name"].split()[-1].lower()
            if not email:
                for e in _EMAIL_RX.findall(html):
                    if surname in e.lower():
                        email, email_conf = e, "official_page"
                        evidence.append(f"Public email on official profile page: {e}")
                        added.append("email:official_page")
                        break
            if not title:
                m = _TITLE_RX.search(html)
                if m:
                    title = m.group(1)
                    evidence.append(f"Title '{title}' on official profile page {purl}")
                    added.append("title")

    # 4. Email pattern guess — only with >=3 evidence signals and a domain
    #    confirmed from real addresses on the official site.
    if not email and len(evidence) >= 3:
        domain = _mail_domain_for(s.get("university", ""))
        if domain:
            import unicodedata
            folded = unicodedata.normalize("NFKD", s["name"]).encode(
                "ascii", "ignore").decode()
            parts = [p for p in folded.lower().split()
                     if p not in ("van", "von", "de", "der", "den") and p.isalpha()]
            if len(parts) >= 2:
                email = f"{parts[0]}.{parts[-1]}@{domain}"
                email_conf = "pattern_guess"
                evidence.append(
                    f"Email GUESSED from confirmed institutional pattern "
                    f"first.last@{domain} — verify before sending")
                added.append("email:pattern_guess")

    metrics["evidence"] = evidence
    score = contact_readiness({**s, "email": email, "title": title,
                               "email_confidence": email_conf,
                               "metrics": metrics})
    metrics["contact_readiness"] = score
    execute("UPDATE supervisors SET email=?, email_confidence=?, title=?, "
            "metrics=? WHERE id=?",
            (email, email_conf, title, json.dumps(metrics), supervisor_id))
    return {"id": supervisor_id, "name": s["name"], "added": added,
            "email": email, "email_confidence": email_conf,
            "contact_readiness": score, "evidence": evidence}


def candidate_report(profile: dict, pos: dict, supervisor_id: int) -> dict:
    """Everything the user needs to judge one candidate at a glance."""
    from app.vetting import outreach_gate
    got = rows("SELECT * FROM supervisors WHERE id=?", (supervisor_id,))
    if not got:
        return {"error": "not found"}
    s = got[0]
    metrics = json.loads(s.get("metrics") or "{}")
    gate = outreach_gate(profile, pos, s)
    return {
        "id": supervisor_id,
        "full_name": s["name"],
        "title": s.get("title") or "",
        "institution": s.get("university") or "",
        "department_faculty": s.get("faculty") or s.get("department") or "",
        "profile_url": s.get("profile_url") or "",
        "public_email": s.get("email") or "",
        "email_confidence": s.get("email_confidence") or "unknown",
        "evidence": metrics.get("evidence") or [],
        "evidence_strength": len(metrics.get("evidence") or []),
        "topical_fit": gate["topic_similarity"],
        "contact_readiness": metrics.get("contact_readiness",
                                         contact_readiness(s)),
        "outreach_allowed": gate["allowed"],
        "gate_reasons": gate["reasons"],
    }


def _mail_domain_for(university: str) -> str:
    u = (university or "").lower()
    for key, dom in _KNOWN_MAIL_DOMAINS.items():
        if key in u:
            return dom
    return ""


def register_mail_domain(university_key: str, domain: str) -> None:
    """Record a mail domain confirmed from a real address on the official site."""
    _KNOWN_MAIL_DOMAINS[university_key.lower()] = domain
