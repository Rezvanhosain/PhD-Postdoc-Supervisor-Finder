"""Open-position sources.

EURAXESS is the primary implemented source (public EU portal, robots-checked,
rate-limited, cached). FindAPhD, Academic Positions and THE Jobs are supported
via best-effort HTML parsers behind the same politeness layer — their markup
changes often, so failures are logged to Manual Review rather than crashing.
Every stored position keeps its source URL and access date."""
from __future__ import annotations

from typing import Callable

from bs4 import BeautifulSoup

from app.db import insert, log_error, now
from app.sources.http import get

def _save(p: dict) -> int:
    return insert("positions", title=p.get("title", ""), university=p.get("university", ""),
                  department=p.get("department", ""), country=p.get("country", ""),
                  deadline=p.get("deadline", ""), eligibility=p.get("eligibility", ""),
                  description=p.get("description", "")[:3000], source=p["source"],
                  source_url=p["source_url"], date_accessed=now())


def search_euraxess(keywords: str, limit: int = 25) -> list[dict]:
    """EURAXESS job search (https://euraxess.ec.europa.eu)."""
    url = "https://euraxess.ec.europa.eu/jobs/search"
    html = get(url, params={"keywords": keywords}, check_robots=True)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    for art in soup.select("article, div.ecl-content-item, li.search-result")[:limit]:
        a = art.find("a", href=True)
        if not a or not a.get_text(strip=True):
            continue
        href = a["href"]
        if href.startswith("/"):
            href = "https://euraxess.ec.europa.eu" + href
        text = art.get_text(" ", strip=True)
        results.append({
            "title": a.get_text(strip=True),
            "university": "", "department": "", "country": "",
            "deadline": "", "eligibility": "",
            "description": text[:1500],
            "source": "euraxess", "source_url": href,
        })
    if not results:
        log_error("scrape", "EURAXESS returned a page but no positions were parsed "
                  "(site markup may have changed).", needs_review=True)
    return results


def search_findaphd(keywords: str, limit: int = 25) -> list[dict]:
    """FindAPhD.com listing search (best effort)."""
    url = "https://www.findaphd.com/phds/"
    html = get(url, params={"Keywords": keywords}, check_robots=True)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("div.phd-result, div.resultsRow, article")[:limit]:
        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if href.startswith("/"):
            href = "https://www.findaphd.com" + href
        title = a.get_text(strip=True)
        inst = card.select_one(".instLink, .phd-result__dept-inst, .institution")
        results.append({
            "title": title, "university": inst.get_text(strip=True) if inst else "",
            "department": "", "country": "", "deadline": "", "eligibility": "",
            "description": card.get_text(" ", strip=True)[:1500],
            "source": "findaphd", "source_url": href,
        })
    if not results:
        log_error("scrape", "FindAPhD parse produced no results — markup may have "
                  "changed or robots.txt disallowed the page.", needs_review=True)
    return results


def search_academic_positions(keywords: str, limit: int = 25) -> list[dict]:
    url = "https://academicpositions.com/find-jobs"
    html = get(url, params={"search": keywords}, check_robots=True)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("a[href*='/ad/'], div.job-item a[href]")[:limit]:
        href = card.get("href", "")
        if href.startswith("/"):
            href = "https://academicpositions.com" + href
        title = card.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        results.append({
            "title": title[:200], "university": "", "department": "", "country": "",
            "deadline": "", "eligibility": "", "description": "",
            "source": "academic_positions", "source_url": href,
        })
    if not results:
        log_error("scrape", "Academic Positions parse produced no results.", needs_review=True)
    return results


def search_the_jobs(keywords: str, limit: int = 25) -> list[dict]:
    url = "https://www.timeshighereducation.com/unijobs/listings/"
    html = get(url, params={"Keywords": keywords}, check_robots=True)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    results = []
    for card in soup.select("div.lister__details, article")[:limit]:
        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if href.startswith("/"):
            href = "https://www.timeshighereducation.com" + href
        results.append({
            "title": a.get_text(strip=True), "university": "", "department": "",
            "country": "", "deadline": "", "eligibility": "",
            "description": card.get_text(" ", strip=True)[:1500],
            "source": "the_jobs", "source_url": href,
        })
    if not results:
        log_error("scrape", "THE Jobs parse produced no results.", needs_review=True)
    return results


SOURCES: dict[str, Callable[[str, int], list[dict]]] = {
    "EURAXESS": search_euraxess,
    "FindAPhD": search_findaphd,
    "Academic Positions": search_academic_positions,
    "THE Jobs": search_the_jobs,
}


def search_all(keywords: str, sources: list[str] | None = None) -> list[dict]:
    """Run selected sources sequentially (politeness > speed), save & return."""
    all_results = []
    for name, fn in SOURCES.items():
        if sources and name not in sources:
            continue
        try:
            found = fn(keywords, 25)
        except Exception as e:
            log_error("scrape", f"{name} search failed: {e}", needs_review=True)
            found = []
        for p in found:
            _save(p)
        all_results.extend(found)
    return all_results
