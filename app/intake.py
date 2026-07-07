"""Semi-automated backup intake (manual URL / manual entry).

When automated discovery finds nothing, the user can paste an opportunity
URL or a batch of supervisor/profile URLs. Extraction is deliberately
best-effort: every extracted field lands in an editable form before saving,
an extraction-confidence score is stored, and failure leaves a blank manual
form usable. Nothing here bypasses the existing vetting/outreach gate —
manual supervisors go through the same person-name validation, and Google
Scholar / arbitrary web text is never treated as verified publication
evidence (verification stays with OpenAlex/Semantic Scholar/Crossref)."""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.db import insert, log_error, now, rows
from app.europe import detect_country
from app.sources.http import get, get_json

# ---------------------------------------------------------------- opportunity

# core fields used for the extraction-confidence score, weighted by how much
# they matter for the downstream workflow
_OPP_WEIGHTS = {"title": 3, "university": 3, "country": 1, "deadline": 2,
                "description": 2, "kind": 1, "eligibility": 1, "funding": 1}

_DEADLINE_RX = re.compile(
    r"(?:deadline|apply(?:\s+by|\s+before)?|closing date|applications? close|"
    r"applications? due)[^.\n]{0,60}?"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}[./]\d{1,2}[./]\d{4})", re.I)

_UNI_RX = re.compile(
    r"\b((?:University|Universität|Universiteit|Université|Università|Universidad)"
    r"\s+(?:of\s+|de\s+|di\s+)?[A-ZÀ-Ž][\w'’-]+(?:\s+[A-ZÀ-Ž][\w'’-]+){0,2}"
    r"|[A-ZÀ-Ž][\w'’-]+(?:\s+[A-ZÀ-Ž][\w'’-]+){0,2}\s+"
    r"(?:University|Universität|Universiteit|Université|Università|Universidad)"
    r"|[A-ZÀ-Ž][\w'’-]+\s+Institute\s+of\s+Technology)")


def _first_sentence_with(text: str, words: tuple[str, ...], maxlen: int = 400) -> str:
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
        low = sent.lower()
        if any(w in low for w in words) and 30 < len(sent) < 600:
            return sent.strip()[:maxlen]
    return ""


def extract_opportunity_fields(html: str, url: str = "") -> dict:
    """Best-effort field extraction from a call/ad page. Pure (no network).

    Returns {"fields": {...}, "confidence": 0..1, "notes": [...]}."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    notes: list[str] = []

    og = soup.find("meta", property="og:title")
    title = (og.get("content", "").strip() if og else "") or \
        (soup.h1.get_text(" ", strip=True) if soup.h1 else "") or \
        (soup.title.get_text(strip=True) if soup.title else "")
    title = title[:200]

    head = title + " " + text[:3000]
    low = head.lower()
    kind = ""
    if re.search(r"\bpost-?doc", low):
        kind = "postdoc"
    elif re.search(r"\bph\.?d\b|\bdoctoral\b|\bdoctorate\b", low):
        kind = "phd"

    m = _UNI_RX.search(head) or _UNI_RX.search(text[:8000])
    university = m.group(1).strip() if m else ""

    country = detect_country(head) or detect_country(text[:5000])

    m = _DEADLINE_RX.search(text)
    deadline = m.group(1).strip() if m else ""

    dep = ""
    md = re.search(r"\b((?:Faculty|Department|School|Institute) of [A-ZÀ-Ž][\w&,' -]{3,60})", text)
    if md:
        dep = md.group(1).strip()

    fields = {
        "title": title,
        "university": university,
        "country": country,
        "department": dep,
        "kind": kind,
        "deadline": deadline,
        "description": text[:1500],
        "eligibility": _first_sentence_with(text, ("eligib", "requirement", "applicants must", "qualification")),
        "funding": _first_sentence_with(text, ("funded", "funding", "salary", "stipend", "scholarship covers", "gross")),
        "documents_required": _first_sentence_with(
            text, ("required documents", "application should include", "application must include",
                   "please submit", "attach the following", "documents:")),
        "source_url": url,
    }
    weight_hit = sum(w for k, w in _OPP_WEIGHTS.items() if fields.get(k))
    confidence = round(weight_hit / sum(_OPP_WEIGHTS.values()), 2)
    for k in ("title", "university", "deadline"):
        if not fields[k]:
            notes.append(f"could not extract {k} — fill it in manually")
    return {"fields": fields, "confidence": confidence, "notes": notes}


def extract_opportunity(url: str) -> dict:
    """Fetch a call/ad URL politely and extract fields. On fetch failure the
    caller keeps a blank manual form; the failure is logged for review."""
    html = get(url, check_robots=True)
    if not html:
        log_error("scrape", f"Manual opportunity import: could not fetch {url}",
                  needs_review=True)
        return {"fields": {"source_url": url}, "confidence": 0.0,
                "notes": ["page could not be fetched (robots.txt, network or HTTP "
                          "error) — enter the details manually"]}
    return extract_opportunity_fields(html, url)


def save_manual_opportunity(fields: dict, source_type: str = "manual_url",
                            confidence: float = 0.0) -> int:
    """Save into the existing positions flow. Returns row id (0 = duplicate URL)."""
    if not (fields.get("title") or "").strip():
        return 0
    return insert(
        "positions",
        title=fields.get("title", "").strip(),
        university=fields.get("university", "").strip(),
        department=fields.get("department", "").strip(),
        country=fields.get("country", "").strip(),
        kind=fields.get("kind", ""),
        deadline=fields.get("deadline", ""),
        eligibility=fields.get("eligibility", ""),
        funding=fields.get("funding", ""),
        description=fields.get("description", ""),
        documents_required=fields.get("documents_required", ""),
        source="manual",
        source_type=source_type,
        extraction_confidence=confidence,
        source_url=(fields.get("source_url") or "").strip() or None,
        date_accessed=now(),
    )


# ---------------------------------------------------------------- supervisors

_ORCID_RX = re.compile(r"orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])")
_OPENALEX_RX = re.compile(r"openalex\.org/(?:authors/)?(A\d+)", re.I)
_S2_RX = re.compile(r"semanticscholar\.org/author/(?:[^/?#]+/)?(\d+)")

_EMAIL_RX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_TITLE_RX = re.compile(
    r"\b(Professor|Prof\.|Associate Professor|Assistant Professor|"
    r"University Lecturer|Senior Researcher|Research Director|Docent)\b", re.I)


def parse_profile_urls(text: str) -> list[str]:
    """One URL per line; ignores blanks and non-URLs; dedups preserving order."""
    out: list[str] = []
    for line in (text or "").splitlines():
        u = line.strip()
        if u and not u.startswith("http"):
            u = "https://" + u if "." in u and " " not in u else ""
        if u and u.startswith("http") and u not in out:
            out.append(u)
    return out


def detect_profile_kind(url: str) -> str:
    if _ORCID_RX.search(url):
        return "orcid"
    if _OPENALEX_RX.search(url):
        return "openalex"
    if _S2_RX.search(url):
        return "semantic_scholar"
    if "scholar.google" in urlparse(url).netloc:
        return "google_scholar"
    return "web"


def parse_orcid_url(url: str) -> str:
    m = _ORCID_RX.search(url)
    return m.group(1).upper() if m else ""


def _blank_candidate(url: str, note: str, confidence: float = 0.0) -> dict:
    return {"name": "", "title": "", "university": "", "department": "",
            "country": "", "email": "", "email_confidence": "unknown",
            "profile_url": url, "research_areas": [], "publications": [],
            "metrics": {}, "source": "manual_import",
            "source_type": "manual_profile_url", "source_url": url,
            "external_id": url, "extraction_confidence": confidence,
            "notes": [note]}


def _candidate_from_orcid(url: str) -> dict:
    oid = parse_orcid_url(url)
    h = {"Accept": "application/json"}
    person = get_json(f"https://pub.orcid.org/v3.0/{oid}/person", headers=h) or {}
    name_o = (person.get("name") or {})
    name = " ".join(filter(None, [
        ((name_o.get("given-names") or {}).get("value") or "").strip(),
        ((name_o.get("family-name") or {}).get("value") or "").strip()]))
    emails = [e.get("email", "") for e in ((person.get("emails") or {}).get("email") or [])]
    emp = get_json(f"https://pub.orcid.org/v3.0/{oid}/employments", headers=h) or {}
    institution = ""
    for group in emp.get("affiliation-group") or []:
        for s in group.get("summaries") or []:
            org = ((s.get("employment-summary") or {}).get("organization") or {})
            if org.get("name"):
                institution = org["name"]
                break
        if institution:
            break
    cand = _blank_candidate(url, "identity from public ORCID record", 0.7 if name else 0.1)
    cand.update(name=name, university=institution,
                metrics={"orcid": oid,
                         "evidence": [f"ORCID record {oid} (pasted by user)"]})
    if emails:
        cand.update(email=emails[0], email_confidence="orcid_public")
    if not name:
        cand["notes"] = ["ORCID record fetched but name not public — enter manually"]
        cand["extraction_confidence"] = 0.1
    return cand


def _candidate_from_openalex(url: str) -> dict:
    aid = _OPENALEX_RX.search(url).group(1)
    a = get_json(f"https://api.openalex.org/authors/{aid}") or {}
    insts = a.get("last_known_institutions") or []
    cand = _blank_candidate(url, "identity from OpenAlex author record",
                            0.7 if a.get("display_name") else 0.0)
    cand.update(
        name=a.get("display_name", ""),
        university=(insts[0].get("display_name", "") if insts else ""),
        country=(insts[0].get("country_code", "") if insts else ""),
        research_areas=[t["display_name"] for t in (a.get("topics") or [])[:8]],
        profile_url=a.get("id") or url,
        external_id=a.get("id") or url,
        metrics={"works_count": a.get("works_count"),
                 "cited_by_count": a.get("cited_by_count"),
                 "h_index": (a.get("summary_stats") or {}).get("h_index")})
    if not cand["name"]:
        cand["notes"] = ["OpenAlex author could not be fetched — enter manually"]
    return cand


def _candidate_from_s2(url: str) -> dict:
    sid = _S2_RX.search(url).group(1)
    a = get_json(f"https://api.semanticscholar.org/graph/v1/author/{sid}",
                 {"fields": "name,affiliations,homepage,paperCount,hIndex"}) or {}
    cand = _blank_candidate(url, "identity from Semantic Scholar author record",
                            0.6 if a.get("name") else 0.0)
    cand.update(name=a.get("name", ""),
                university=(a.get("affiliations") or [""])[0],
                profile_url=a.get("homepage") or url,
                metrics={"s2_id": sid, "s2_paper_count": a.get("paperCount"),
                         "h_index": a.get("hIndex")})
    if not cand["name"]:
        cand["notes"] = ["Semantic Scholar author could not be fetched — enter manually"]
    return cand


def extract_supervisor_from_html(html: str, url: str) -> dict:
    """Generic profile/staff-page extraction. Pure (no network). Best-effort:
    name from h1/title, academic title, surname-matching public email."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    raw_name = (soup.h1.get_text(" ", strip=True) if soup.h1 else "") or \
        (soup.title.get_text(strip=True).split("|")[0].split("—")[0].split(" - ")[0]
         if soup.title else "")
    # strip leading academic titles from the heading
    name = re.sub(r"^(?:(?:Prof(?:essor)?|Dr|Assoc(?:iate)?|Assistant|PD|habil)\.?\s+)+",
                  "", raw_name.strip())[:80]
    text = soup.get_text(" ", strip=True)
    tm = _TITLE_RX.search(text[:4000])
    title = tm.group(1) if tm else ""
    email, email_conf = "", "unknown"
    surname = (name.split() or [""])[-1].lower()
    if len(surname) > 2:
        for e in _EMAIL_RX.findall(html):
            if surname in e.lower():
                email, email_conf = e, "official_page"
                break
    cand = _blank_candidate(url, "best-effort extraction from pasted web page",
                            0.5 if name and (title or email) else 0.25 if name else 0.0)
    cand.update(name=name, title=title, email=email, email_confidence=email_conf,
                metrics={"evidence": [f"profile page pasted by user: {url}"]})
    if not name:
        cand["notes"] = ["no person name found on the page — enter manually"]
    return cand


def supervisor_from_url(url: str) -> dict:
    """Route one pasted URL to the right extractor. Returns an editable
    candidate dict (never raises; failures come back as low-confidence blanks)."""
    kind = detect_profile_kind(url)
    try:
        if kind == "orcid":
            return _candidate_from_orcid(url)
        if kind == "openalex":
            return _candidate_from_openalex(url)
        if kind == "semantic_scholar":
            return _candidate_from_s2(url)
        if kind == "google_scholar":
            c = _blank_candidate(
                url, "Google Scholar pages are not scraped (terms of service); "
                     "enter the person's details manually — Scholar listings are "
                     "NOT treated as verified publication evidence", 0.0)
            return c
        html = get(url, check_robots=True)
        if not html:
            return _blank_candidate(url, "page could not be fetched — enter manually")
        return extract_supervisor_from_html(html, url)
    except Exception as e:  # any extractor bug degrades to manual entry
        log_error("supervisor", f"Manual profile import failed for {url}: {e}")
        return _blank_candidate(url, f"extraction failed ({e}) — enter manually")


def save_manual_supervisor(cand: dict) -> dict:
    """Save one manual/imported supervisor through the existing vetting.

    URL-derived candidates must pass full validate_supervisor. A deliberate
    manual entry (source_type='manual_entry') may lack source signals — the
    user's attestation stands in for one — but a non-person name is still
    rejected. Returns {"id": int, "reasons": [...]}."""
    from app.sources.university import save_supervisor
    from app.vetting import person_name_check, validate_supervisor

    cand = dict(cand)
    ok, why = person_name_check(cand.get("name", ""))
    if not ok:
        log_error("supervisor", f"Rejected manual supervisor entry: {why}")
        return {"id": 0, "reasons": [why]}
    metrics = dict(cand.get("metrics") or {})
    metrics["extraction_confidence"] = cand.get("extraction_confidence", 0.0)
    cand["metrics"] = metrics
    if cand.get("email") and cand.get("email_confidence") in ("unknown", "", None):
        # user-typed address: not verified, but explicitly not a guess
        cand["email_confidence"] = "manual_entry"
    cand.setdefault("source_type", "manual_entry")

    v = validate_supervisor(cand)
    if not v["valid"] and cand["source_type"] == "manual_entry":
        # user-attested manual entry: allow, but record honestly that no
        # independent source signal exists yet
        metrics["evidence"] = (v.get("evidence") or []) + \
            ["manually entered by user — no independent source signal yet; "
             "enrich via ORCID/OpenAlex before outreach"]
        sid = insert(
            "supervisors",
            name=cand["name"], title=cand.get("title", ""),
            university=cand.get("university", ""), faculty=cand.get("faculty", ""),
            department=cand.get("department", ""), country=cand.get("country", ""),
            email=cand.get("email", ""),
            email_confidence=cand.get("email_confidence", "unknown"),
            profile_url=cand.get("profile_url", ""),
            research_areas=json.dumps(cand.get("research_areas", [])),
            publications="[]",  # never trust pasted text as publication evidence
            metrics=json.dumps(metrics),
            supervises_phd="unknown", source="manual_entry",
            source_type="manual_entry", source_url=cand.get("source_url", ""),
            date_accessed=now(),
            external_id=cand.get("external_id") or f"manual:{cand['name']}:{now()}",
        )
        return {"id": sid, "reasons": ["saved as unvetted manual entry — "
                                       "no independent identity signal"]}
    if not v["valid"]:
        log_error("supervisor", f"Rejected manual supervisor import "
                  f"'{cand.get('name','')}': " + "; ".join(v["reasons"]))
        return {"id": 0, "reasons": v["reasons"]}
    sid = save_supervisor(cand, position_id=int(cand.get("position_id") or 0))
    return {"id": sid, "reasons": v["reasons"]}


# ---------------------------------------------------------------- linking

def link_and_check(profile: dict, position_id: int, supervisor_ids: list[int]) -> list[dict]:
    """Link a saved opportunity to supervisors: run fit scoring, topical fit,
    contact-readiness and the outreach gate; persist fit_scores rows.
    Returns one report per supervisor with allowed/blocked reasons."""
    from app.db import execute
    from app.fit import score_fit
    from app.sources.enrich import candidate_report

    got = rows("SELECT * FROM positions WHERE id=?", (position_id,))
    if not got:
        return []
    pos = got[0]
    reports: list[dict] = []
    for sid in supervisor_ids:
        sgot = rows("SELECT * FROM supervisors WHERE id=?", (sid,))
        if not sgot:
            continue
        sup = sgot[0]
        # adopt the opportunity as this supervisor's linked position if unset
        if not sup.get("position_id"):
            execute("UPDATE supervisors SET position_id=? WHERE id=?",
                    (position_id, sid))
        fit = score_fit(profile, pos, sup)
        execute("DELETE FROM fit_scores WHERE position_id=? AND supervisor_id=?",
                (position_id, sid))
        insert("fit_scores", position_id=position_id, supervisor_id=sid,
               score=fit["score"], recommendation=fit["recommendation"],
               outreach_useful=int(fit["outreach_useful"]),
               reasons=json.dumps(fit), created_at=now())
        rep = candidate_report(profile, pos, sid)
        rep["fit"] = fit
        reports.append(rep)
    return reports
