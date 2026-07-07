"""Supervisor identity vetting and the outreach safety gate.

Two failure modes this module exists to prevent, both observed live:
  * page chrome scraped as people ("Tuotantotalous Faculty", a funding-scheme
    eponym like "Jean Monnet") being stored as supervisors, and
  * outreach drafts addressed to such artifacts — a real applicant could send
    an email to a person who does not exist.

Rules:
  1. A supervisor record is stored only if its name passes person-name
     validation AND at least one supporting source signal backs it
     (OpenAlex author record, official page with an academic title,
     surname-matching public email, or a person-specific profile URL).
  2. No outreach draft is generated unless identity validation passes,
     the supervisor's institution matches the opportunity's, and topical
     fit clears a threshold. A missing recipient email never silently
     produces an empty To: field — it is explicitly reported.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

# Words that mark an organisational unit, not a person. Matched per token so
# "Tuotantotalous Faculty" or "Doctoral School" fail even with novel words.
_ORG_WORDS = {
    "faculty", "department", "institute", "institut", "center", "centre",
    "school", "university", "college", "program", "programme", "group",
    "laboratory", "lab", "unit", "office", "team", "service", "network",
    "academy", "library", "council", "foundation", "association", "society",
    "committee", "board", "division", "doctoral", "graduate", "campus",
    "research", "sciences", "studies", "engineering", "administration",
    "admissions", "management", "chair", "professorship", "fellowship",
    "scholarship", "grant", "project", "cluster", "consortium", "alliance",
    # role/title words scraped alongside a real name ("Marius Muench Assistant"
    # was stored live and pattern-guessed an email for a non-existent person)
    "assistant", "associate", "professor", "lecturer", "docent", "dean",
    "director", "coordinator", "researcher", "fellow", "student", "candidate",
    "postdoc", "postdoctoral", "supervisor", "tutor", "head", "manager",
    "officer", "editor", "emeritus", "secretary",
}

# Funding schemes / institutional eponyms that look like person names but are
# never the person you would email. Exact full-name matches only, so a real
# researcher who happens to share a surname is not blocked.
_SCHEME_NAMES = {
    "jean monnet", "marie curie", "marie sklodowska-curie",
    "marie skłodowska-curie", "erasmus mundus", "horizon europe",
    "max planck", "alexander von humboldt", "fraunhofer gesellschaft",
}

_NAME_TOKEN_RX = re.compile(r"^[A-ZÀ-Ž][a-zà-žA-ZÀ-Ž'’.-]*$")

# URLs that are search/listing pages, not a person's profile.
_GENERIC_URL_RX = re.compile(r"(search[?/]|search_type=|[?&]page=|/jobs?/|/vacanc)", re.I)


def person_name_check(name: str) -> tuple[bool, str]:
    """Is this plausibly a person's full name? Returns (ok, reason)."""
    name = (name or "").strip()
    if not name:
        return False, "empty name"
    if name.lower() in _SCHEME_NAMES:
        return False, f"'{name}' is a funding scheme / institutional eponym, not a contactable person"
    tokens = name.split()
    if not 2 <= len(tokens) <= 5:
        return False, f"'{name}' does not have 2-5 name tokens"
    for t in tokens:
        if t.lower().strip(".") in _ORG_WORDS:
            return False, f"'{name}' contains organisational word '{t}'"
        if not _NAME_TOKEN_RX.match(t) and t.lower() not in ("van", "von", "de", "der", "den", "da", "di", "del", "la", "le", "ter", "ten"):
            return False, f"'{name}' token '{t}' is not name-like"
    if name.isupper():
        return False, f"'{name}' is all-caps (likely a heading, not a name)"
    return True, "name is person-like"


def _is_person_profile_url(url: str) -> bool:
    if not url:
        return False
    if _GENERIC_URL_RX.search(url):
        return False
    # OpenAlex author IDs are person-specific by construction
    if "openalex.org/A" in url:
        return True
    path = urlparse(url).path
    return len(path.strip("/")) > 1


def validate_supervisor(s: dict) -> dict:
    """Full identity validation: person-like name + >=1 supporting signal.

    Returns {"valid": bool, "reasons": [...], "evidence": [...]} where
    evidence lists the concrete signals that back this identity."""
    reasons: list[str] = []
    evidence: list[str] = []

    ok, why = person_name_check(s.get("name", ""))
    if not ok:
        return {"valid": False, "reasons": [why], "evidence": []}
    evidence.append(why)

    metrics = s.get("metrics") or {}
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics or "{}")
        except json.JSONDecodeError:
            metrics = {}

    signals = 0
    ext = s.get("external_id") or ""
    if "openalex.org/A" in ext and metrics.get("works_count"):
        signals += 1
        evidence.append(
            f"OpenAlex author record {ext} with {metrics.get('works_count')} works "
            f"affiliated to {s.get('university','the institution')}")
    title = (s.get("title") or "").strip()
    if s.get("source_type") == "official" and title:
        signals += 1
        evidence.append(f"Official university page lists academic title '{title}' "
                        f"at {s.get('source_url','')}")
    email = (s.get("email") or "").strip()
    surname = (s.get("name", "").split() or [""])[-1].lower()
    if email and surname and surname in email.lower():
        signals += 1
        evidence.append(f"Public email {email} matches surname")
    profile_url = s.get("profile_url") or ""
    if _is_person_profile_url(profile_url):
        signals += 1
        evidence.append(f"Person-specific profile URL: {profile_url}")
    else:
        reasons.append(f"profile URL is generic or missing: '{profile_url or '(none)'}'")

    if signals == 0:
        reasons.append("no supporting source signal (no OpenAlex record, no official "
                       "title, no matching email, no person-specific profile URL)")
        return {"valid": False, "reasons": reasons, "evidence": evidence}
    return {"valid": True, "reasons": reasons, "evidence": evidence}


def institution_match(sup_university: str, pos_university: str) -> bool:
    """Loose token match so 'Tampere University' == 'Tampereen yliopisto' fails
    honestly but 'University of Helsinki' == 'Helsinki University' passes."""
    a = {w for w in re.findall(r"[a-zà-ž]{4,}", (sup_university or "").lower())
         if w not in ("university", "universität", "universiteit", "universita")}
    b = {w for w in re.findall(r"[a-zà-ž]{4,}", (pos_university or "").lower())
         if w not in ("university", "universität", "universiteit", "universita")}
    if not a or not b:
        return False
    return bool(a & b)


def contact_readiness(s: dict) -> int:
    """0-100 score: how ready is this candidate to be contacted, given the
    evidence on file? Weighted toward verified email and corroborated identity.

      identity signals (max 40): 10 per distinct evidence source class
      email (max 40): verified/scraped-from-official 40, orcid_public 40,
                      pattern_guess 15, none 0
      profile URL person-specific (10), academic title known (10)"""
    metrics = s.get("metrics") or {}
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics or "{}")
        except json.JSONDecodeError:
            metrics = {}
    score = 0
    classes = set()
    for e in (metrics.get("evidence") or []):
        el = e.lower()
        if "openalex" in el:
            classes.add("openalex")
        elif "orcid" in el:
            classes.add("orcid")
        elif "semantic scholar" in el:
            classes.add("s2")
        elif "official" in el:
            classes.add("official")
    score += min(40, 10 * len(classes))
    email = (s.get("email") or "").strip()
    conf = s.get("email_confidence") or "unknown"
    if email:
        score += 15 if conf == "pattern_guess" else 40
    if _is_person_profile_url(s.get("profile_url") or ""):
        score += 10
    if (s.get("title") or "").strip():
        score += 10
    return min(100, score)


TOPIC_FIT_THRESHOLD = 0.05
# Calibrated live (2026-07): raw CV text is dominated by narrow proper nouns
# (org names, "East Africa"), so TF-IDF under-scores field-level adjacency —
# a genuinely adjacent nonprofit-sector researcher scored 0.04 while every
# unrelated math/physics supervisor scored <=0.014. Appending the curated
# field vocabulary to the candidate side widens that gap (adjacent 0.084 vs
# junk <=0.014); 0.05 sits in the middle of it.


def _gate_profile_text(profile: dict) -> str:
    """Candidate text for the topical-fit check: CV-derived profile text
    enriched with the field taxonomy, so adjacency within the candidate's
    discipline registers even when exact CV phrases don't recur."""
    from app.field import _POSITIVE
    from app.matching import profile_text
    field_terms = " ".join(t for t, w in _POSITIVE.items() if w >= 1.5)
    return profile_text(profile) + " " + field_terms


def outreach_gate(profile: dict, pos: dict, sup: dict) -> dict:
    """Safety gate run before any outreach draft is created.

    Returns {"allowed": bool, "checks": {...}, "reasons": [...],
             "recipient_email": "present"|"missing"}."""
    from app.matching import tfidf_similarity

    checks: dict[str, bool] = {}
    reasons: list[str] = []

    v = validate_supervisor(sup)
    checks["identity"] = v["valid"]
    if not v["valid"]:
        reasons += [f"identity: {r}" for r in v["reasons"]]

    checks["institution"] = institution_match(
        sup.get("university", ""), pos.get("university", ""))
    if not checks["institution"]:
        reasons.append(
            f"institution: supervisor '{sup.get('university','?')}' does not match "
            f"opportunity '{pos.get('university','?')}'")

    metrics = sup.get("metrics") or {}
    if isinstance(metrics, str):
        try:
            metrics = json.loads(metrics or "{}")
        except json.JSONDecodeError:
            metrics = {}
    mismatch = metrics.get("orcid_affiliation_mismatch")
    checks["affiliation_consistent"] = not mismatch
    if mismatch:
        reasons.append(
            f"affiliation: this person's ORCID record names only other "
            f"institution(s) ({', '.join(mismatch[:2])}) — they may have moved, "
            f"or this may be a same-name collision; verify on the official "
            f"{pos.get('university','institution')} staff page before contacting")

    areas = sup.get("research_areas") or "[]"
    if isinstance(areas, str):
        try:
            areas = json.loads(areas or "[]")
        except json.JSONDecodeError:
            areas = []
    pubs = sup.get("publications") or "[]"
    if isinstance(pubs, str):
        try:
            pubs = json.loads(pubs or "[]")
        except json.JSONDecodeError:
            pubs = []
    sup_text = " ".join(areas) + " " + " ".join(p.get("title", "") for p in pubs)
    sim = tfidf_similarity(_gate_profile_text(profile), sup_text) if sup_text.strip() else 0.0
    checks["topical_fit"] = sim >= TOPIC_FIT_THRESHOLD
    if not checks["topical_fit"]:
        reasons.append(f"topical fit: similarity {sim:.2f} between your profile and this "
                       f"supervisor's documented work is below the {TOPIC_FIT_THRESHOLD} "
                       f"threshold — an outreach email here would read as generic")

    conf = sup.get("email_confidence") or "unknown"
    if not (sup.get("email") or "").strip():
        recipient = "missing"
    elif conf == "pattern_guess":
        recipient = "guessed"
        reasons.append("recipient email: address is a pattern GUESS from the "
                       "institutional format — verify it on the official profile "
                       "page and mark it verified before a draft can be created")
    else:
        recipient = "present"
    if recipient == "missing":
        reasons.append("recipient email: no public address on file — find it on the "
                       "official profile page before a draft can be created")
    # A guessed or missing address blocks draft creation outright: a draft
    # with a fabricated To: line is exactly the embarrassing mistake this
    # gate exists to prevent. 'manual_verified' (user checked the official
    # page) and scraped/ORCID addresses count as present.
    checks["recipient_email"] = recipient == "present"

    allowed = (checks["identity"] and checks["institution"]
               and checks["affiliation_consistent"]
               and checks["topical_fit"] and checks["recipient_email"])
    return {"allowed": allowed, "checks": checks, "reasons": reasons,
            "recipient_email": recipient, "topic_similarity": round(sim, 3)}
