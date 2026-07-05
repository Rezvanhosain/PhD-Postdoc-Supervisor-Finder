"""Fit scoring: shortlist-only, explainable components, outreach logic."""
import json

from app import db
from app.fit import run_fit_for_shortlist, score_fit

PROFILE = {
    "target_level": "PhD",
    "target_countries": ["HU"],
    "research_areas": ["strategic management", "organizational behaviour"],
    "keywords": ["business management"],
    "publications": ["Strategic decision making in SMEs (2023)"],
    "skills": ["quantitative methods", "survey research"],
}

POS = {
    "id": 1, "title": "PhD in Business and Management",
    "university": "Corvinus University of Budapest", "country": "HU",
    "kind": "phd", "deadline": "", "description":
        "Doctoral programme in strategic management and organizational studies.",
    "classification": "supervisor_required", "class_confidence": 0.8,
    "class_source_official": 1,
}


def test_score_fit_components_and_outreach():
    r = score_fit(PROFILE, POS)
    assert 0 <= r["score"] <= 100
    assert r["outreach_required"] is True
    assert r["outreach_useful"] is True
    assert "components" in r and "opportunity_similarity" in r["components"]
    assert "Admission path" in r["why"]
    assert r["recommendation"] in ("strong", "moderate", "weak", "avoid")


def test_level_mismatch_flagged():
    pos = dict(POS, kind="postdoc", classification="open_call_postdoc")
    r = score_fit(PROFILE, pos)
    assert r["components"]["level_fit"] < 1
    assert any("level" in x.lower() for x in r["risks"])


def test_supervisor_pair_scoring():
    sup = {"id": 5, "name": "Anna Kovacs", "email": "",
           "source_type": "unofficial",
           "research_areas": json.dumps(["strategic management", "SME growth"]),
           "publications": json.dumps([{"title": "Organizational behaviour in SMEs"}])}
    r = score_fit(PROFILE, POS, sup)
    assert r["components"]["supervisor_similarity"] is not None
    assert any("bibliometric" in x for x in r["risks"])
    assert any("email" in x.lower() for x in r["risks"])


def test_run_fit_only_on_shortlist():
    db.execute("DELETE FROM positions")
    db.execute("DELETE FROM supervisors")
    db.execute("DELETE FROM fit_scores")
    db.insert("positions", title="Shortlisted PhD", university="U1", country="HU",
              kind="phd", shortlisted=1, description="management research",
              source="t", source_url="https://x/1")
    db.insert("positions", title="Ignored PhD", university="U2", country="DE",
              kind="phd", shortlisted=0, description="physics",
              source="t", source_url="https://x/2")
    n = run_fit_for_shortlist(PROFILE)
    assert n == 1
    fits = db.rows("SELECT * FROM fit_scores")
    assert len(fits) == 1
    assert fits[0]["supervisor_id"] == 0
