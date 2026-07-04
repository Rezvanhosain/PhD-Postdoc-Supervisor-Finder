import json

from app.matching import (deadline_urgency, keyword_overlap, score_position,
                          score_supervisor, tfidf_similarity)

PROFILE = {
    "name": "Test Candidate",
    "research_areas": ["microfinance", "NGO accountability", "nonprofit governance"],
    "keywords": ["development studies", "accounting", "social impact"],
    "publications": ["Microfinance and poverty reduction in East Africa (2022)"],
    "skills": ["quantitative methods", "STATA"],
    "target_countries": ["GB"],
    "target_level": "PhD",
}


def test_keyword_overlap_basic():
    assert keyword_overlap("microfinance ngo governance", "ngo governance studies") > 0.5
    assert keyword_overlap("apples oranges", "quantum physics") == 0.0
    assert keyword_overlap("", "anything") == 0.0


def test_tfidf_similarity_orders_sensibly():
    cand = "microfinance nonprofit governance accountability"
    close = "governance and accountability in nonprofit microfinance institutions"
    far = "deep learning for protein folding prediction"
    assert tfidf_similarity(cand, close) > tfidf_similarity(cand, far)


def test_score_supervisor_relevant_beats_irrelevant():
    relevant = {
        "research_areas": json.dumps(["microfinance", "nonprofit governance"]),
        "publications": json.dumps([{"title": "NGO accountability in developing countries"}]),
        "country": "GB", "email": "x@uni.ac.uk",
    }
    irrelevant = {
        "research_areas": json.dumps(["quantum computing"]),
        "publications": json.dumps([{"title": "Qubit error correction"}]),
        "country": "US", "email": "",
    }
    r1 = score_supervisor(PROFILE, relevant)
    r2 = score_supervisor(PROFILE, irrelevant)
    assert r1["score"] > r2["score"]
    assert "components" in r1 and r1["components"]["method"].startswith("tfidf")


def test_score_supervisor_flags_missing_data():
    empty = {"research_areas": "[]", "publications": "[]", "country": "", "email": ""}
    r = score_supervisor(PROFILE, empty)
    assert r["confidence"] == "low"
    assert any("publication data" in risk.lower() or "email" in risk.lower()
               for risk in r["risks"])


def test_score_position_level_mismatch_penalized():
    phd_pos = {"title": "PhD studentship in nonprofit governance",
               "description": "microfinance accountability NGO", "country": "GB",
               "deadline": "", "eligibility": ""}
    postdoc_pos = dict(phd_pos, title="Postdoc in nonprofit governance")
    r_phd = score_position(PROFILE, phd_pos)
    r_pd = score_position(PROFILE, postdoc_pos)
    assert r_phd["score"] > r_pd["score"]
    assert any("deadline" in risk.lower() for risk in r_phd["risks"])


def test_deadline_urgency():
    score, note = deadline_urgency("")
    assert score == 0.5
    score, note = deadline_urgency("2020-01-01")
    assert score == 0.0 and "passed" in note
    score, note = deadline_urgency("2099-12-31")
    assert score == 1.0
    score, note = deadline_urgency("not a date")
    assert "check manually" in note.lower() or "could not parse" in note.lower()
