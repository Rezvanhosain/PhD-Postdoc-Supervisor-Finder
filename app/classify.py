"""Admission-path classification (workflow step 2).

Every opportunity is classified into one of five admission paths. The
classifier is rule-based and evidence-preserving: each label comes with a
confidence, the exact text snippet that triggered it, the URL it came from,
and whether that URL is an official university page or a third-party portal.

Policy: third-party sources are fine for *discovery*, but when an official
university/faculty/admissions page is available its classification wins over
a third-party one. Uncertain results are flagged for manual review."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.db import execute, log_error, rows
from app.sources.http import get

LABELS = {
    "supervisor_required": "Supervisor contact mandatory before application",
    "supervisor_recommended": "Supervisor contact recommended (not mandatory)",
    "direct_application": "Direct application first, supervisor match later",
    "named_pi_postdoc": "Postdoc with a named PI / research group",
    "open_call_postdoc": "Open-call postdoc (PI targeting still helps)",
}

# Third-party discovery portals — everything else that looks academic is
# treated as potentially official.
THIRD_PARTY_HOSTS = (
    "euraxess.ec.europa.eu", "findaphd.com", "findapostdoc.com",
    "academicpositions.com", "timeshighereducation.com", "jobs.ac.uk",
    "academictransfer.com", "researchgate.net", "linkedin.com", "indeed.",
    "glassdoor.", "scholarshipdb.", "phdportal.com", "mastersportal.com",
)

_OFFICIAL_HINTS = re.compile(
    r"(\.edu$|\.edu\.|\.ac\.[a-z]{2}$|\.ac\.[a-z]{2}\.|^uni-|\.uni-|"
    r"universit|hochschule|polytech|\.cnrs\.|\.mpg\.|\.cern$)", re.I)

# (pattern, label, weight) — evaluated against lowercased text.
_RULES: list[tuple[str, str, float]] = [
    # supervisor mandatory
    (r"must (first )?(contact|find|secure|identify)[^.]{0,80}supervisor", "supervisor_required", 1.0),
    (r"supervisor[^.]{0,60}(must|is required|is mandatory) [^.]{0,60}appl", "supervisor_required", 0.9),
    (r"(agreement|approval|acceptance|confirmation)[^.]{0,50}(of|from)[^.]{0,40}supervisor", "supervisor_required", 0.9),
    (r"\b(must|required to|need to|have to)\b[^.]{0,40}(contact|approach)[^.]{0,50}supervisor[^.]{0,60}before (you )?(submit|apply)", "supervisor_required", 1.0),
    (r"applications? without [^.]{0,40}supervisor[^.]{0,50}(not|cannot) be", "supervisor_required", 1.0),
    (r"letter of (acceptance|support) from [^.]{0,40}supervisor", "supervisor_required", 0.9),
    # supervisor recommended
    (r"(encouraged|advised|advisable|recommended|welcome|invited) to (contact|approach)[^.]{0,60}(supervisor|potential supervisor|academic)", "supervisor_recommended", 0.9),
    (r"may (wish to )?(contact|identify)[^.]{0,50}supervisor", "supervisor_recommended", 0.7),
    (r"informal (enquiries|inquiries|contact)[^.]{0,60}(supervisor|professor|dr\.?|prof\.?)", "supervisor_recommended", 0.7),
    # direct application
    (r"apply (online|now|directly|via|through)[^.]{0,60}(portal|system|website|link|form)?", "direct_application", 0.5),
    (r"(submit|send) your application (via|through|to|online)", "direct_application", 0.7),
    (r"(application|admissions?) (portal|deadline|form|system)", "direct_application", 0.5),
    (r"supervisors? (are|will be) (assigned|allocated|matched)", "direct_application", 1.0),
    (r"no need to (contact|find)[^.]{0,40}supervisor", "direct_application", 1.0),
    (r"(doctoral|graduate) school[^.]{0,60}(admission|application|call)", "direct_application", 0.6),
    # named-PI postdoc
    (r"postdoc[^.]{0,120}(in the (group|lab|laboratory|team) of|led by|under the (supervision|direction) of)", "named_pi_postdoc", 1.0),
    (r"(group|lab|laboratory|team) of (prof|dr|professor)\.? [a-z]", "named_pi_postdoc", 0.8),
    (r"(principal investigator|pi)[:\s][^.]{0,60}(prof|dr)", "named_pi_postdoc", 0.8),
    # open-call postdoc
    (r"(open call|open topic|fellowship (programme|program)|your own (research )?(project|proposal))[^.]{0,80}(postdoc|fellow)", "open_call_postdoc", 0.9),
    (r"postdoc[^.]{0,100}(open call|any (research )?(area|field|discipline)|choose (a|your) host)", "open_call_postdoc", 0.9),
    (r"(msca|marie sk?[lł]odowska|humboldt|walter benjamin|individual fellowship)", "open_call_postdoc", 0.8),
]
_COMPILED = [(re.compile(p, re.I), label, w) for p, label, w in _RULES]


def is_official_url(url: str) -> bool:
    host = urlparse(url or "").netloc.lower()
    if not host:
        return False
    if any(tp in host for tp in THIRD_PARTY_HOSTS):
        return False
    return bool(_OFFICIAL_HINTS.search(host))


def is_postdoc(pos: dict) -> bool:
    text = f"{pos.get('title','')} {pos.get('description','')}".lower()
    return ("postdoc" in text or "post-doc" in text or "postdoctoral" in text) \
        and "phd position" not in (pos.get("title") or "").lower()


def classify_text(text: str, postdoc: bool | None = None) -> tuple[str, float, str]:
    """Score all rules against one text. Returns (label, confidence, evidence)."""
    low = (text or "").lower()
    scores: dict[str, float] = {}
    evidence: dict[str, str] = {}
    for rx, label, w in _COMPILED:
        m = rx.search(low)
        if m:
            scores[label] = scores.get(label, 0.0) + w
            if label not in evidence:
                start = max(0, m.start() - 60)
                evidence[label] = text[start:m.end() + 100].strip()
    if postdoc:
        # a postdoc can't be a PhD admission path
        for k in ("supervisor_required", "direct_application"):
            scores.pop(k, None)
        if not scores:
            return "open_call_postdoc", 0.3, "No explicit PI wording found — defaulted to open call."
    if not scores:
        return "direct_application", 0.2, "No explicit supervisor-contact wording found — defaulted to direct application. Verify on the official page."
    label = max(scores, key=lambda k: scores[k])
    conf = min(1.0, scores[label] / 1.5)
    return label, round(conf, 2), evidence.get(label, "")


def _official_links(html: str, base_url: str, limit: int = 3) -> list[str]:
    """Extract candidate official-university links from a third-party ad page."""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return []
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if is_official_url(href) and href not in out:
            out.append(href)
        if len(out) >= limit:
            break
    return out


def _page_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(" ", strip=True)[:20000]
    except Exception:
        return ""


def classify_position(pos: dict, fetch: bool = True) -> dict:
    """Classify one opportunity. Prefers official pages over third-party text.

    Returns {label, label_text, confidence, evidence, source_url, source_official}.
    """
    postdoc = is_postdoc(pos)
    candidates: list[tuple[str, str, bool]] = []  # (text, url, official)

    desc = pos.get("description") or ""
    src_url = pos.get("source_url") or ""
    if desc:
        candidates.append((desc, src_url, is_official_url(src_url)))

    if fetch and src_url:
        html = get(src_url, check_robots=True)
        if html:
            candidates.append((_page_text(html), src_url, is_official_url(src_url)))
            if not is_official_url(src_url):
                for link in _official_links(html, src_url):
                    off_html = get(link, check_robots=True)
                    if off_html:
                        candidates.append((_page_text(off_html), link, True))
    if pos.get("official_url"):
        off_html = get(pos["official_url"], check_robots=True) if fetch else None
        if off_html:
            candidates.append((_page_text(off_html), pos["official_url"], True))

    best: dict | None = None
    best_official: dict | None = None
    for text, url, official in candidates:
        label, conf, ev = classify_text(text, postdoc)
        item = {"label": label, "confidence": conf, "evidence": ev,
                "source_url": url, "source_official": official}
        if official and (best_official is None or conf > best_official["confidence"]):
            best_official = item
        if best is None or conf > best["confidence"]:
            best = item

    # Official wins whenever it produced a usable (non-default) answer.
    chosen = best_official if (best_official and best_official["confidence"] >= 0.3) else best
    if chosen is None:
        chosen = {"label": "open_call_postdoc" if postdoc else "direct_application",
                  "confidence": 0.1, "evidence": "No text available to classify.",
                  "source_url": src_url, "source_official": False}
    if chosen["confidence"] < 0.4:
        log_error("classify", f"Low-confidence classification for '{pos.get('title','?')[:80]}'",
                  f"label={chosen['label']} conf={chosen['confidence']}", needs_review=True)
    chosen["label_text"] = LABELS.get(chosen["label"], chosen["label"])
    chosen["kind"] = "postdoc" if postdoc else "phd"
    return chosen


def classify_and_store(position_id: int, fetch: bool = True) -> dict | None:
    got = rows("SELECT * FROM positions WHERE id=?", (position_id,))
    if not got:
        return None
    result = classify_position(got[0], fetch=fetch)
    execute("UPDATE positions SET kind=?, classification=?, class_confidence=?, "
            "class_evidence=?, class_source_url=?, class_source_official=? WHERE id=?",
            (result["kind"], result["label"], result["confidence"],
             result["evidence"][:1000], result["source_url"],
             int(result["source_official"]), position_id))
    return result
