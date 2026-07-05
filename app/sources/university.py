"""University-constrained supervisor/PI discovery (workflow step 4).

Fixes the core v1 problem: supervisor search returned unrelated people from
anywhere. Here, every query starts from a *selected* university:

1. The university is resolved to an OpenAlex institution (ID, ROR, homepage,
   country) so bibliometric results can be hard-filtered to that institution.
2. OpenAlex works at that institution matching the topic yield authors whose
   current affiliation is that institution — never authors from elsewhere.
3. The official university website is crawled (politely, robots-checked) for
   staff/faculty/doctoral-school pages; people found there are marked
   source_type='official' and merged with the bibliometric records.

Every stored supervisor keeps: source_type (official|unofficial), faculty,
profile URL, and a link to the position that triggered the search."""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.db import execute, insert, log_error, now, rows
from app.sources.http import get, get_json

OA = "https://api.openalex.org"

_PEOPLE_LINK_HINTS = re.compile(
    r"(staff|faculty|people|team|member|professor|research(er|-group|group)?|"
    r"doctoral|phd|graduate-school|department|institute|lab)", re.I)

_EMAIL_RX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
# "Prof. Dr. Anna Kovács" / "Dr Jane O'Neill-Smith" style
_PERSON_RX = re.compile(
    r"\b((?:Prof(?:essor)?\.?|Dr\.?|Assoc(?:iate)?\.? ?Prof\.?|PD Dr\.?)"
    r"(?: (?:Dr|h\.c|mult|em|ir|habil)\.?)*"
    r" [A-ZÀ-Ž][a-zà-ž]+(?:[ -][A-ZÀ-Ž][a-zà-žA-ZÀ-Ž'’-]+){1,3})")


def resolve_institution(name: str) -> dict | None:
    """Resolve a university name to an OpenAlex institution record."""
    data = get_json(f"{OA}/institutions", {"search": name, "per-page": 5})
    for inst in (data or {}).get("results", []):
        if inst.get("type") in (None, "education", "facility", "government"):
            return {
                "id": inst.get("id", ""),
                "name": inst.get("display_name", name),
                "country": inst.get("country_code", ""),
                "homepage": inst.get("homepage_url", "") or "",
                "ror": inst.get("ror", ""),
            }
    return None


def authors_at_institution(inst: dict, topic: str, limit: int = 20) -> list[dict]:
    """Authors at *this institution only*, working on the topic.

    Route: topic-matched recent works filtered by the institution ID, then
    authors whose latest known institution is still that institution."""
    inst_id = inst["id"].rstrip("/").split("/")[-1]
    data = get_json(f"{OA}/works", {
        "search": topic, "per-page": 40,
        "filter": f"authorships.institutions.id:{inst_id},from_publication_date:2018-01-01",
        "sort": "relevance_score:desc"})
    author_ids: list[str] = []
    for w in (data or {}).get("results", []):
        for au in (w.get("authorships") or []):
            inst_ids = [i.get("id", "") for i in (au.get("institutions") or [])]
            if any(inst_id in (i or "") for i in inst_ids):
                aid = (au.get("author") or {}).get("id")
                if aid and aid not in author_ids:
                    author_ids.append(aid)
    if not author_ids:
        return []
    short = "|".join(a.rstrip("/").split("/")[-1] for a in author_ids[:50])
    data = get_json(f"{OA}/authors", {
        "filter": f"ids.openalex:{short},last_known_institutions.id:{inst_id},works_count:>3",
        "per-page": limit})
    out = []
    for a in (data or {}).get("results", []):
        topics = [t["display_name"] for t in (a.get("topics") or [])[:8]]
        out.append({
            "name": a.get("display_name", ""),
            "title": "",
            "university": inst["name"],
            "faculty": "",
            "department": "",
            "country": inst.get("country", ""),
            "email": "", "email_confidence": "unknown",
            "profile_url": a.get("id", ""),
            "research_areas": topics,
            "publications": [],
            "metrics": {"works_count": a.get("works_count"),
                        "cited_by_count": a.get("cited_by_count"),
                        "h_index": (a.get("summary_stats") or {}).get("h_index")},
            "supervises_phd": "unknown",
            "source": "openalex", "source_type": "unofficial",
            "source_url": a.get("id", ""), "external_id": a.get("id", ""),
        })
    return out


def _same_site(url: str, homepage: str) -> bool:
    h1 = urlparse(url).netloc.lower().removeprefix("www.")
    h2 = urlparse(homepage).netloc.lower().removeprefix("www.")
    root = ".".join(h2.split(".")[-2:]) if h2 else ""
    return bool(root) and h1.endswith(root)


def find_people_pages(homepage: str, topic: str, max_pages: int = 4) -> list[str]:
    """Find likely staff/faculty/doctoral-school pages on the official site."""
    if not homepage:
        return []
    html = get(homepage, check_robots=True)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    topic_words = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", topic)}
    scored: list[tuple[int, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(homepage, a["href"]).split("#")[0]
        if href in seen or not _same_site(href, homepage):
            continue
        seen.add(href)
        label = f"{a.get_text(' ', strip=True)} {href}".lower()
        score = 0
        if _PEOPLE_LINK_HINTS.search(label):
            score += 2
        score += sum(1 for w in topic_words if w in label)
        if score >= 2:
            scored.append((score, href))
    scored.sort(reverse=True)
    return [u for _, u in scored[:max_pages]]


def people_from_official_page(url: str, university: str, country: str) -> list[dict]:
    """Extract person records from an official staff/faculty page. Best-effort:
    names with academic titles, nearby profile links and public emails."""
    html = get(url, check_robots=True)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    people: dict[str, dict] = {}
    for m in _PERSON_RX.finditer(text):
        full = re.sub(r"\s+", " ", m.group(1)).strip()
        # split title from name
        parts = full.split()
        title_parts, name_parts = [], []
        for p in parts:
            if p.rstrip(".").lower() in ("prof", "professor", "dr", "assoc", "associate", "pd", "habil", "em", "ir", "h.c", "mult"):
                title_parts.append(p)
            else:
                name_parts.append(p)
        name = " ".join(name_parts)
        if len(name.split()) < 2 or name in people:
            continue
        people[name] = {
            "name": name, "title": " ".join(title_parts),
            "university": university, "faculty": "", "department": "",
            "country": country, "email": "", "email_confidence": "unknown",
            "profile_url": url, "research_areas": [], "publications": [],
            "metrics": {}, "supervises_phd": "likely" if "doctoral" in url.lower() or "phd" in url.lower() else "unknown",
            "source": "official_page", "source_type": "official",
            "source_url": url, "external_id": f"official:{url}#{name}",
        }
    # try to attach emails that sit near a name (same page, surname match)
    emails = set(_EMAIL_RX.findall(html))
    for name, p in people.items():
        surname = name.split()[-1].lower()
        for e in emails:
            if surname and surname in e.lower():
                p["email"] = e
                p["email_confidence"] = "scraped"
                break
    return list(people.values())


def save_supervisor(s: dict, position_id: int = 0) -> int:
    return insert(
        "supervisors",
        name=s["name"], title=s.get("title", ""), university=s.get("university", ""),
        faculty=s.get("faculty", ""), department=s.get("department", ""),
        country=s.get("country", ""), email=s.get("email", ""),
        email_confidence=s.get("email_confidence", "unknown"),
        profile_url=s.get("profile_url", ""),
        research_areas=json.dumps(s.get("research_areas", [])),
        publications=json.dumps(s.get("publications", [])),
        metrics=json.dumps(s.get("metrics", {})),
        supervises_phd=s.get("supervises_phd", "unknown"),
        source=s.get("source", ""), source_type=s.get("source_type", "unofficial"),
        source_url=s.get("source_url", ""), date_accessed=now(),
        external_id=s.get("external_id") or s.get("source_url"),
        position_id=position_id,
    )


def find_supervisors_for_position(position_id: int, topic: str,
                                  max_bibliometric: int = 15) -> dict:
    """Orchestrator: for one shortlisted opportunity, find supervisors/PIs
    constrained to its university. Returns counts + institution info."""
    got = rows("SELECT * FROM positions WHERE id=?", (position_id,))
    if not got:
        return {"error": "position not found", "official": 0, "bibliometric": 0}
    pos = got[0]
    uni = (pos.get("university") or "").strip()
    if not uni:
        return {"error": "This opportunity has no university name stored — set it "
                "first (edit the row) so the search can be constrained.",
                "official": 0, "bibliometric": 0}
    inst = resolve_institution(uni)
    n_official = n_biblio = 0
    if inst:
        for s in authors_at_institution(inst, topic, limit=max_bibliometric):
            if save_supervisor(s, position_id):
                n_biblio += 1
        homepage = inst.get("homepage", "")
        for page in find_people_pages(homepage, topic):
            for p in people_from_official_page(page, inst["name"], inst.get("country", "")):
                if save_supervisor(p, position_id):
                    n_official += 1
    else:
        log_error("supervisor", f"Could not resolve institution '{uni}' via OpenAlex.",
                  needs_review=True)
    # if the ad page itself is official, mine it for named PIs too
    src = pos.get("source_url") or ""
    from app.classify import is_official_url
    if is_official_url(src):
        for p in people_from_official_page(src, uni, pos.get("country", "")):
            if save_supervisor(p, position_id):
                n_official += 1
    return {"institution": inst, "official": n_official, "bibliometric": n_biblio}


def fetch_publications(supervisor_id: int, limit: int = 5) -> int:
    """Fetch 3-5 recent verified publications for one supervisor (OpenAlex)."""
    from app.sources import openalex
    got = rows("SELECT * FROM supervisors WHERE id=?", (supervisor_id,))
    if not got:
        return 0
    s = got[0]
    ext = s.get("external_id") or ""
    if "openalex.org/A" in ext:
        works = openalex.author_recent_works(ext, limit=limit)
    else:
        # official-page person: match by name at same institution
        data = get_json(f"{OA}/authors", {"search": s["name"], "per-page": 3})
        works = []
        for a in (data or {}).get("results", []):
            insts = a.get("last_known_institutions") or []
            if any((s.get("university") or "").lower()[:12] in (i.get("display_name") or "").lower()
                   for i in insts):
                works = openalex.author_recent_works(a["id"], limit=limit)
                break
    if works:
        execute("UPDATE supervisors SET publications=? WHERE id=?",
                (json.dumps(works[:limit]), supervisor_id))
    return len(works)
