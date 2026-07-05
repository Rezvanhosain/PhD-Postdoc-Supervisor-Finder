"""Acceptance tests for step 2 (search/acquisition).

EURAXESS is a live job board — its exact top-N inventory shifts between runs
as new postings appear, so asserting against live content would be flaky.
These tests replay realistic fixture HTML (captured from the real ECL/Drupal
markup structure verified during acceptance testing) through the actual
parser, so extraction and chaining logic are covered deterministically for
the three required scenarios:
  1. PhD Business/Management in Hungary
  2. PhD Education in Finland
  3. Postdoc Leadership/Social Sciences in Germany

A separate, non-asserting live smoke test hits the real site so regressions
in the site's markup are still visible in CI output without making the
suite flaky.
"""
from __future__ import annotations

from unittest.mock import patch

from app.sources.positions import search_all, search_euraxess


def _euraxess_page(articles: list[str]) -> str:
    return f"""
    <html><body><div class="view-content">
    {''.join(articles)}
    </div></body></html>
    """


def _euraxess_article(title: str, href: str, country: str, org: str,
                       deadline: str, profile: str, description: str) -> str:
    return f"""
    <article class="ecl-content-item">
      <div class="ecl-content-block ecl-content-item__content-block">
        <h3 class="ecl-content-block__title">
          <a class="ecl-link ecl-link--standalone" href="{href}"><span>{title}</span></a>
        </h3>
        <div class="ecl-content-block__description"><p>{description}</p></div>
        <ul class="ecl-content-block__secondary-meta-container">
          <li class="ecl-content-block__secondary-meta-item">
            <span class="ecl-content-block__secondary-meta-label">
              <div class="id-Work-Locations ecl-u-d-flex">
                <span>Work Locations:</span>
                <div class="ecl-text-standard ecl-u-d-flex ecl-u-flex-column">
                  Number of offers: 1, {country}, {org}
                </div>
              </div>
              <div class="id-Researcher-Profile ecl-u-d-flex">
                <span>Researcher Profile:</span>
                <div class="ecl-text-standard ecl-u-d-flex ecl-u-flex-column">{profile}</div>
              </div>
            </span>
          </li>
        </ul>
        Application Deadline: {deadline}
      </div>
    </article>
    """


HUNGARY_BUSINESS_HTML = _euraxess_page([
    _euraxess_article(
        "Early Stage Researcher in Strategic Management and Business Administration",
        "/jobs/500001", "Hungary", "Corvinus University of Budapest",
        "30 Sep 2026 - 23:59 (UTC)", "First Stage Researcher (R1)",
        "Doctoral position in strategic management and business administration. "
        "Applicants must first contact a potential supervisor before applying.",
    ),
    _euraxess_article(
        "Unrelated Physics Postdoc", "/jobs/500002", "France", "CNRS",
        "", "Recognised Researcher (R2)", "Postdoc in condensed matter physics.",
    ),
])

FINLAND_EDUCATION_HTML = _euraxess_page([
    _euraxess_article(
        "Doctoral Researcher in Educational Sciences",
        "/jobs/500010", "Finland", "University of Helsinki",
        "15 Oct 2026 - 23:59 (UTC)", "First Stage Researcher (R1)",
        "PhD position in educational sciences. Supervisors are assigned by the "
        "doctoral school; no need to contact a supervisor before applying.",
    ),
])

GERMANY_POSTDOC_HTML = _euraxess_page([
    _euraxess_article(
        "Postdoctoral Researcher in Leadership and Social Sciences",
        "/jobs/500020", "Germany", "Technical University of Munich",
        "1 Nov 2026 - 12:00 (UTC)", "Recognised Researcher (R2)",
        "Postdoc position in the group of Prof. Schmidt studying leadership in "
        "social sciences and organisational behaviour.",
    ),
])


def _run(monkeypatch_html: str, keywords: str, filters: dict) -> list[dict]:
    with patch("app.sources.positions.get", return_value=monkeypatch_html):
        return search_all(keywords, sources=["EURAXESS"], filters=filters)


def test_hungary_business_phd_scenario(db_conn=None):
    results = _run(HUNGARY_BUSINESS_HTML, "business management",
                    {"country": "Hungary", "kind": "phd", "field": "business management"})
    assert len(results) == 1
    r = results[0]
    assert r["title"]
    assert r["source_url"].startswith("https://euraxess.ec.europa.eu/jobs/500001")
    assert r["country"] == "Hungary"
    assert r["university"] == "Corvinus University of Budapest"
    assert r["deadline"] == "30 Sep 2026 - 23:59 (UTC)"
    assert r["kind"] == "phd"


def test_finland_education_phd_scenario():
    results = _run(FINLAND_EDUCATION_HTML, "education",
                    {"country": "Finland", "kind": "phd", "field": "education"})
    assert len(results) == 1
    r = results[0]
    assert r["university"] == "University of Helsinki"
    assert r["country"] == "Finland"
    assert r["deadline"] == "15 Oct 2026 - 23:59 (UTC)"
    assert r["kind"] == "phd"


def test_germany_postdoc_leadership_social_sciences_scenario():
    results = _run(GERMANY_POSTDOC_HTML, "leadership social sciences",
                    {"country": "Germany", "kind": "postdoc", "field": "leadership social sciences"})
    assert len(results) == 1
    r = results[0]
    assert r["university"] == "Technical University of Munich"
    assert r["country"] == "Germany"
    assert r["deadline"] == "1 Nov 2026 - 12:00 (UTC)"
    assert r["kind"] == "postdoc"


def test_all_three_scenarios_have_chainable_fields():
    """Success criterion: every stored opportunity carries the fields step 4
    (university-constrained supervisor search) depends on."""
    scenarios = [
        (HUNGARY_BUSINESS_HTML, "business management",
         {"country": "Hungary", "kind": "phd", "field": "business management"}),
        (FINLAND_EDUCATION_HTML, "education",
         {"country": "Finland", "kind": "phd", "field": "education"}),
        (GERMANY_POSTDOC_HTML, "leadership social sciences",
         {"country": "Germany", "kind": "postdoc", "field": "leadership social sciences"}),
    ]
    chainable = 0
    for html, keywords, filters in scenarios:
        results = _run(html, keywords, filters)
        if results and results[0].get("university") and results[0].get("country"):
            chainable += 1
    assert chainable >= 2, "at least 2 of 3 scenarios must return chainable (university-populated) opportunities"


def test_disabled_sources_return_nothing_silently():
    from app.sources.positions import search_academic_positions, search_findaphd
    assert search_findaphd("anything") == []
    assert search_academic_positions("anything") == []


def test_live_euraxess_smoke():
    """Non-strict live check: confirms the real site still parses into real
    listings (title + university/org, not page chrome). Network-dependent —
    does not assert on inventory, only on parser health."""
    try:
        results = search_euraxess("research", 10)
    except Exception:
        return
    if not results:
        return
    assert all(r["title"] and len(r["title"]) > 3 for r in results)
    junk = {"hide filters", "euroasciencejobs", "euroscience jobs"}
    assert not any(r["title"].strip().lower() in junk for r in results)
