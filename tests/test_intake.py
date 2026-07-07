"""Manual intake: URL extraction, fallback, vetting, ORCID parsing, linking."""
import json

from app import db, intake

OPP_HTML = """
<html><head><title>PhD position in Development Studies | University of Helsinki</title>
<meta property="og:title" content="Doctoral Researcher in Development Studies"></head>
<body><nav>menu</nav>
<h1>Doctoral Researcher in Development Studies</h1>
<p>The Faculty of Social Sciences at the University of Helsinki, Finland invites
applications for a fully funded PhD position on NGO accountability and
international development.</p>
<p>Eligibility: applicants must hold a master's degree in social sciences or a
related field with good grades.</p>
<p>The position is fully funded for four years with a monthly salary of 2500 EUR.</p>
<p>Please submit the following required documents: CV, motivation letter,
transcripts and two references.</p>
<p>Application deadline: 2026-09-30 at 23:59 EET.</p>
</body></html>
"""

SUP_HTML = """
<html><head><title>Prof. Anna Virtanen — University of Helsinki</title></head>
<body><h1>Prof. Anna Virtanen</h1>
<p>Professor of Development Studies, Faculty of Social Sciences.</p>
<p>Contact: anna.virtanen@helsinki.fi</p></body></html>
"""


def test_opportunity_extraction_from_fixture_html():
    res = intake.extract_opportunity_fields(OPP_HTML, "https://uni.example/job/1")
    f = res["fields"]
    assert f["title"] == "Doctoral Researcher in Development Studies"
    assert "Helsinki" in f["university"]
    assert f["country"] == "FI"
    assert f["kind"] == "phd"
    assert f["deadline"] == "2026-09-30"
    assert "master's degree" in f["eligibility"]
    assert "funded" in f["funding"].lower()
    assert "required documents" in f["documents_required"].lower()
    assert res["confidence"] >= 0.7


def test_opportunity_fallback_when_fetch_fails(monkeypatch):
    monkeypatch.setattr(intake, "get", lambda *a, **k: None)
    res = intake.extract_opportunity("https://dead.example/x")
    assert res["confidence"] == 0.0
    assert res["fields"]["source_url"] == "https://dead.example/x"
    assert any("manually" in n for n in res["notes"])
    # manual save still works with user-typed fields
    pid = intake.save_manual_opportunity(
        {"title": "Hand-entered PhD call", "university": "Test University",
         "source_url": "https://dead.example/x"}, "manual_url", 0.0)
    assert pid > 0
    row = db.rows("SELECT * FROM positions WHERE id=?", (pid,))[0]
    assert row["source_type"] == "manual_url"
    assert row["extraction_confidence"] == 0.0


def test_multiple_supervisor_urls_parsed_into_candidates(monkeypatch):
    urls = intake.parse_profile_urls(
        "https://uni.example/staff/virtanen\n\n"
        "https://orcid.org/0000-0002-1825-0097\n"
        "https://scholar.google.com/citations?user=abc123\n"
        "not a url\n"
        "https://uni.example/staff/virtanen\n")  # dup dropped
    assert len(urls) == 3
    monkeypatch.setattr(intake, "get", lambda *a, **k: SUP_HTML)
    cand = intake.supervisor_from_url("https://uni.example/staff/virtanen")
    assert cand["name"] == "Anna Virtanen"
    assert cand["title"] == "Professor"
    assert cand["email"] == "anna.virtanen@helsinki.fi"
    assert cand["extraction_confidence"] > 0
    # Google Scholar: never scraped, comes back manual-only with a warning
    gs = intake.supervisor_from_url("https://scholar.google.com/citations?user=abc123")
    assert gs["name"] == ""
    assert gs["publications"] == []
    assert any("not treated as verified" in n.lower() for n in gs["notes"])


def test_orcid_url_parsing():
    assert intake.parse_orcid_url("https://orcid.org/0000-0002-1825-0097") == \
        "0000-0002-1825-0097"
    assert intake.detect_profile_kind("https://orcid.org/0000-0002-1825-0097") == "orcid"
    assert intake.detect_profile_kind("https://openalex.org/A5023888391") == "openalex"
    assert intake.detect_profile_kind(
        "https://www.semanticscholar.org/author/Jane-Doe/12345") == "semantic_scholar"
    assert intake.detect_profile_kind("https://uni.example/people/x") == "web"
    assert intake.parse_orcid_url("https://uni.example/no-orcid") == ""


def test_manual_supervisor_entry_validation():
    # valid person, deliberate manual entry with no source signal -> saved,
    # but honestly flagged as unvetted
    res = intake.save_manual_supervisor(
        {"name": "Anna Virtanen", "university": "University of Helsinki",
         "source_type": "manual_entry"})
    assert res["id"] > 0
    row = db.rows("SELECT * FROM supervisors WHERE id=?", (res["id"],))[0]
    assert row["source_type"] == "manual_entry"
    ev = json.loads(row["metrics"])["evidence"]
    assert any("manually entered" in e for e in ev)
    # user-typed email is recorded as manual_entry confidence, not verified
    res2 = intake.save_manual_supervisor(
        {"name": "Bob Jansen", "email": "bob@x.example",
         "source_type": "manual_entry"})
    row2 = db.rows("SELECT * FROM supervisors WHERE id=?", (res2["id"],))[0]
    assert row2["email_confidence"] == "manual_entry"


def test_non_person_artifact_rejected():
    for bad in ("Faculty of Social Sciences", "Jean Monnet", "Doctoral School"):
        res = intake.save_manual_supervisor({"name": bad, "source_type": "manual_entry"})
        assert res["id"] == 0, bad
    assert not db.rows("SELECT * FROM supervisors WHERE name='Jean Monnet'")


def test_linking_runs_gate_and_blocks_guessed_email():
    profile = {"name": "Cand", "target_level": "PhD",
               "research_areas": ["international development", "NGO accountability"],
               "keywords": []}
    pid = intake.save_manual_opportunity(
        {"title": "PhD in International Development", "university": "University of Helsinki",
         "country": "FI", "description": "international development NGO accountability "
         "civil society development studies"}, "manual_url", 0.8)
    sid = intake.save_manual_supervisor(
        {"name": "Anna Virtanen", "title": "Professor",
         "university": "University of Helsinki",
         "email": "anna.virtanen@helsinki.fi",
         "profile_url": "https://helsinki.fi/people/anna-virtanen",
         "research_areas": ["international development", "civil society",
                            "NGO accountability", "development studies"],
         "source_type": "manual_profile_url", "email_confidence": "official_page"})["id"]
    assert sid > 0
    reports = intake.link_and_check(profile, pid, [sid])
    assert len(reports) == 1
    rep = reports[0]
    assert "outreach_allowed" in rep and "gate_reasons" in rep
    assert rep["fit"]["score"] >= 0
    assert db.rows("SELECT * FROM fit_scores WHERE position_id=? AND supervisor_id=?",
                   (pid, sid))
    # pattern-guessed email must block outreach until manually verified
    db.execute("UPDATE supervisors SET email_confidence='pattern_guess' WHERE id=?", (sid,))
    rep2 = intake.link_and_check(profile, pid, [sid])[0]
    assert rep2["outreach_allowed"] is False
    assert any("GUESS" in r for r in rep2["gate_reasons"])
    db.execute("UPDATE supervisors SET email_confidence='manual_verified' WHERE id=?", (sid,))
    rep3 = intake.link_and_check(profile, pid, [sid])[0]
    assert not any("GUESS" in r for r in rep3["gate_reasons"])
