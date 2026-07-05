"""Open-position sources.

EURAXESS is the only source with a working, maintained parser — a public EU
portal with stable structured markup (robots-checked, rate-limited, cached).
FindAPhD and Academic Positions block scraping (HTTP 403) and are disabled
rather than pretending to work. THE Jobs still responds but its markup gives
no structured university/country/deadline fields, so it is kept as a
degraded, best-effort supplementary source. Every stored position keeps its
source URL and access date."""
from __future__ import annotations

import re
from typing import Callable

from bs4 import BeautifulSoup

from app.db import insert, log_error, now
from app.europe import detect_country, is_europe, to_code
from app.sources.http import get


def _derive_kind(p: dict) -> str:
    text = f"{p.get('title','')} {p.get('description','')}".lower()
    if "postdoc" in text or "post-doc" in text or "postdoctoral" in text:
        return "postdoc"
    if "phd" in text or "doctoral" in text or "doctorate" in text:
        return "phd"
    return ""


def _save(p: dict) -> int:
    country = p.get("country") or detect_country(
        f"{p.get('title','')} {p.get('description','')}")
    return insert("positions", title=p.get("title", ""), university=p.get("university", ""),
                  department=p.get("department", ""), country=country,
                  deadline=p.get("deadline", ""), eligibility=p.get("eligibility", ""),
                  description=p.get("description", "")[:3000], source=p["source"],
                  source_url=p["source_url"], date_accessed=now(),
                  kind=p.get("kind") or _derive_kind(p),
                  funding=p.get("funding", ""), field=p.get("field", ""))


_DEADLINE_RX = re.compile(r"Application Deadline:\s*\|?\s*([^|]+)")


def _euraxess_kind(title: str, profile_text: str) -> str:
    """R1 (First Stage Researcher, up to PhD) -> phd; R2-R4 -> postdoc,
    falling back to keyword detection in the title when the profile is absent
    or ambiguous (a listing can carry both tags)."""
    kind = _derive_kind({"title": title})
    if kind:
        return kind
    if "R1" in profile_text:
        return "phd"
    if any(r in profile_text for r in ("R2", "R3", "R4")):
        return "postdoc"
    return ""


def _parse_euraxess_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    for art in soup.select("article.ecl-content-item"):
        title_a = art.select_one("h3.ecl-content-block__title a") or art.select_one("h3 a")
        if not title_a or not title_a.get_text(strip=True):
            continue
        href = title_a["href"].strip()
        if href.startswith("/"):
            href = "https://euraxess.ec.europa.eu" + href

        university, country = "", ""
        loc = art.select_one(".id-Work-Locations .ecl-text-standard")
        if loc:
            parts = [p.strip() for p in loc.get_text(" ", strip=True).split(",") if p.strip()]
            # ["Number of offers: N", country, organisation, city?]
            if len(parts) >= 2:
                country = parts[1]
            if len(parts) >= 3:
                university = parts[2]

        profile_el = art.select_one(".id-Researcher-Profile .ecl-text-standard")
        profile_text = profile_el.get_text(" ", strip=True) if profile_el else ""

        full_text = art.get_text(" | ", strip=True)
        m = _DEADLINE_RX.search(full_text)
        deadline = m.group(1).strip() if m else ""

        desc_el = art.select_one(".ecl-content-block__description")
        description = desc_el.get_text(" ", strip=True) if desc_el else art.get_text(" ", strip=True)

        results.append({
            "title": title_a.get_text(strip=True),
            "university": university, "department": "", "country": country,
            "deadline": deadline, "eligibility": profile_text,
            "description": description[:1500],
            "kind": _euraxess_kind(title_a.get_text(strip=True), profile_text),
            "source": "euraxess", "source_url": href,
        })
    return results


def search_euraxess(keywords: str, limit: int = 25) -> list[dict]:
    """EURAXESS job search (https://euraxess.ec.europa.eu).

    Real listings live in <article class="ecl-content-item"> blocks with a
    stable ECL (Europa Component Library) structure: h3 title link, a
    "Work Locations" field of the form "Number of offers: N, <country>,
    <organisation>[, <city>]", a "Researcher Profile" (R1-R4) field, and an
    "Application Deadline" field. Nothing here is page chrome.

    NOTE: the plain "keywords" query param is silently ignored by this
    Drupal facets view — it always returns the default recent-jobs listing
    (confirmed by requesting distinctive terms and getting identical
    results). The view's actual full-text facet parameter is "f[0]",
    verified by submitting the real HTML search form once and inspecting
    the resulting redirect URL — not a spoofed/brittle header trick.

    The site's full-text facet appears to AND every word in the query, so
    a narrow country+field phrase can under-return even when matching
    positions exist further down the result list. To compensate, this
    pages through up to 3 result pages (still politeness-throttled by the
    shared http layer) rather than only reading page 1."""
    url = "https://euraxess.ec.europa.eu/jobs/search"
    results: list[dict] = []
    for page in range(3):
        html = get(url, params={"f[0]": f"keywords:{keywords}", "page": page}, check_robots=True)
        if not html:
            break
        page_results = _parse_euraxess_page(html)
        if not page_results:
            break
        results.extend(page_results)
        if len(results) >= limit:
            break
    results = results[:limit]
    if not results:
        log_error("scrape", "EURAXESS returned a page but no positions were parsed "
                  "(site markup may have changed).", needs_review=True)
    return results


def search_findaphd(keywords: str, limit: int = 25) -> list[dict]:
    """FindAPhD.com listing search — DISABLED.

    findaphd.com returns HTTP 403 to this client on every request (confirmed
    across many keyword combinations during acceptance testing). Rather than
    scrape around that block with spoofed headers, it is disabled: it always
    returns []. Kept as a function so it can be re-enabled if the site
    changes its bot policy."""
    log_error("scrape", "FindAPhD is disabled: the site returns HTTP 403 to "
              "this client and cannot be scraped reliably.", needs_review=False)
    return []


def search_academic_positions(keywords: str, limit: int = 25) -> list[dict]:
    """Academic Positions listing search — DISABLED for the same reason as
    FindAPhD: consistent HTTP 403. See search_findaphd."""
    log_error("scrape", "Academic Positions is disabled: the site returns "
              "HTTP 403 to this client and cannot be scraped reliably.", needs_review=False)
    return []


def search_the_jobs(keywords: str, limit: int = 25) -> list[dict]:
    """THE (Times Higher Education) unijobs listing search — best effort,
    supplementary. Structured fields available: title (h3 a), university
    (.lister__meta-item--recruiter), location (.lister__meta-item--location,
    "city, country"), description (.lister__description). No deadline field
    is present on the listing page (would need a per-listing fetch), so
    deadline is left blank rather than guessed."""
    url = "https://www.timeshighereducation.com/unijobs/listings/"
    html = get(url, params={"Keywords": keywords}, check_robots=True)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("div.lister__details")[:limit]:
        a = card.find("a", href=True)
        if not a or not a.get_text(strip=True):
            continue
        href = a["href"].strip()
        if href.startswith("/"):
            href = "https://www.timeshighereducation.com" + href

        recruiter = card.select_one(".lister__meta-item--recruiter")
        university = recruiter.get_text(" ", strip=True) if recruiter else ""

        loc_el = card.select_one(".lister__meta-item--location")
        country = ""
        if loc_el:
            loc_parts = [p.strip() for p in loc_el.get_text(" ", strip=True).split(",") if p.strip()]
            if loc_parts:
                country = loc_parts[-1]

        desc_el = card.select_one(".lister__description")
        description = desc_el.get_text(" ", strip=True) if desc_el else card.get_text(" ", strip=True)

        results.append({
            "title": a.get_text(strip=True), "university": university, "department": "",
            "country": country, "deadline": "", "eligibility": "",
            "description": description[:1500],
            "source": "the_jobs", "source_url": href,
        })
    if not results:
        log_error("scrape", "THE Jobs parse produced no results.", needs_review=True)
    return results


SOURCES: dict[str, Callable[[str, int], list[dict]]] = {
    "EURAXESS": search_euraxess,
    "THE Jobs": search_the_jobs,
}

# Disabled — confirmed HTTP 403 on every request during acceptance testing.
# Present for future re-enablement, not registered in SOURCES so the UI does
# not offer a source that cannot return results.
DISABLED_SOURCES: dict[str, Callable[[str, int], list[dict]]] = {
    "FindAPhD": search_findaphd,
    "Academic Positions": search_academic_positions,
}


def _passes(p: dict, filters: dict) -> bool:
    """Post-scrape filtering: Europe-only always; then user filters."""
    text = f"{p.get('title','')} {p.get('university','')} {p.get('description','')}".lower()
    country = p.get("country") or detect_country(text)
    if country and not is_europe(country):
        return False
    want_cc = to_code(filters.get("country") or "")
    if want_cc and country and to_code(country) != want_cc:
        return False
    if want_cc and not country:
        # unknown country: keep only if the country name appears in the text
        from app.europe import country_name
        if country_name(want_cc).lower() not in text:
            return False
    kind = filters.get("kind") or ""
    if kind and (p.get("kind") or _derive_kind(p)) not in ("", kind):
        return False
    uni = (filters.get("university") or "").strip().lower()
    if uni and uni not in text:
        return False
    field = (filters.get("field") or "").strip().lower()
    if field and not any(w in text for w in field.split()):
        return False
    return True


def search_all(keywords: str, sources: list[str] | None = None,
               filters: dict | None = None) -> list[dict]:
    """Run selected sources sequentially (politeness > speed), filter to
    Europe + user filters, save & return.

    Query strategy (verified against live EURAXESS behaviour): the search
    facet does relevance ranking, NOT strict AND — a phrase like
    "leadership social sciences" returns a full page of diverse results
    rather than only exact all-word matches, and searching a country name
    alone returns overwhelmingly that country's listings (e.g. "Finland" ->
    ~28/30 Finland, "Germany" -> ~17/30 Germany). So to actually surface a
    narrow country+field scenario we run several real queries and merge:
      1. keywords (+field),
      2. the country name alone (strong per-country recall),
      3. country + first keyword (co-occurrence boost),
      4. first keyword alone (broad recall for >2-word phrases).
    All are deduped by URL, then the structured country/field is enforced
    by _passes() so precision is not lost."""
    filters = filters or {}
    q = keywords
    if filters.get("field") and filters["field"].lower() not in keywords.lower():
        q = f"{keywords} {filters['field']}".strip()
    queries = [q]
    words = q.split()
    country = (filters.get("country") or "").strip()
    if country:
        # country name alone gives the strongest per-country recall; the
        # post-filter still enforces the exact country, so this only helps.
        queries.append(country)
        if words:
            queries.append(f"{country} {words[0]}")
    if len(words) > 2:
        queries.append(words[0])
    all_results = []
    seen_urls: set[str] = set()
    for name, fn in SOURCES.items():
        if sources and name not in sources:
            continue
        found: list[dict] = []
        for query in queries:
            try:
                found.extend(fn(query, 40))
            except Exception as e:
                log_error("scrape", f"{name} search failed: {e}", needs_review=True)
        deduped = []
        for p in found:
            if p["source_url"] in seen_urls:
                continue
            seen_urls.add(p["source_url"])
            deduped.append(p)
        kept = [p for p in deduped if _passes(p, filters)]
        for p in kept:
            _save(p)
        all_results.extend(kept)
    return all_results
