"""Acceptance tests for supervisor identity vetting and the outreach gate.

The junk names asserted here ("Jean Monnet", "Tuotantotalous Faculty") are
real artifacts that were scraped from a live Tampere University search page
and stored as supervisors before vetting existed."""
from __future__ import annotations

from app.vetting import (institution_match, outreach_gate, person_name_check,
                         validate_supervisor)


def test_rejects_real_observed_artifacts():
    for junk in ("Jean Monnet", "Tuotantotalous Faculty", "Doctoral School",
                 "Marie Curie", "Research Group Leader", "Graduate Program"):
        ok, _ = person_name_check(junk)
        assert not ok, junk


def test_accepts_real_person_names():
    for name in ("Salla Atkins", "Eija Vinnari", "Jane O'Neill-Smith",
                 "Anna Kovács", "Pieter van den Berg"):
        ok, why = person_name_check(name)
        assert ok, f"{name}: {why}"


def test_person_name_alone_is_not_enough():
    """A person-like name with no supporting source signal must not be stored."""
    v = validate_supervisor({"name": "John Smith", "profile_url":
                             "https://uni.example/search?search_type=people"})
    assert not v["valid"]
    assert any("no supporting source signal" in r for r in v["reasons"])


def test_openalex_record_is_sufficient_evidence():
    v = validate_supervisor({
        "name": "Salla Atkins", "external_id": "https://openalex.org/A5021453051",
        "profile_url": "https://openalex.org/A5021453051",
        "metrics": {"works_count": 142}, "university": "Tampere University"})
    assert v["valid"]
    assert any("OpenAlex author record" in e for e in v["evidence"])


def test_institution_match():
    assert institution_match("University of Helsinki", "Helsinki University")
    assert not institution_match("Aalto University", "Tampere University")
    assert not institution_match("", "Tampere University")


def _profile():
    return {"research_areas": ["microfinance", "NGO accountability"],
            "keywords": ["microfinance", "accountability", "nonprofit"]}


def _good_sup():
    return {"name": "Eija Vinnari", "university": "Tampere University",
            "external_id": "https://openalex.org/A123",
            "metrics": {"works_count": 59},
            "profile_url": "https://openalex.org/A123",
            "email": "eija.vinnari@tuni.fi",
            "research_areas": ["NGO accountability", "microfinance institutions",
                               "nonprofit accounting"],
            "publications": [{"title": "Microfinance accountability", "verified": True}]}


def test_gate_allows_aligned_pair():
    g = outreach_gate(_profile(), {"university": "Tampere University"}, _good_sup())
    assert g["allowed"] and g["recipient_email"] == "present"


def test_gate_blocks_low_topical_fit():
    sup = _good_sup()
    sup["research_areas"] = ["quantum photonics", "semiconductor lasers"]
    sup["publications"] = []
    g = outreach_gate(_profile(), {"university": "Tampere University"}, sup)
    assert not g["allowed"] and not g["checks"]["topical_fit"]


def test_gate_blocks_institution_mismatch():
    g = outreach_gate(_profile(), {"university": "Aalto University"}, _good_sup())
    assert not g["allowed"] and not g["checks"]["institution"]


def test_gate_allows_adjacent_field_supervisor():
    """Calibration regression: a nonprofit-sector researcher whose work is
    adjacent to (not identical with) the candidate's niche must pass topical
    fit. Modelled on Helen Abnett (Birmingham), who scored 0.04 under the raw
    representation and was wrongly blocked at the old 0.10 threshold."""
    sup = _good_sup()
    sup["research_areas"] = ["Nonprofit Sector and Volunteering",
                             "Community Development and Social Impact",
                             "Public Policy and Administration Research"]
    sup["publications"] = [
        {"title": "Reflections on using charity annual reporting data"},
        {"title": "Regulatory reform and the creation of national charities"}]
    g = outreach_gate(_profile(), {"university": "Tampere University"}, sup)
    assert g["checks"]["topical_fit"], g["topic_similarity"]
    assert g["allowed"]


def test_gate_still_blocks_unrelated_field_at_calibrated_threshold():
    """The relaxed threshold must not admit off-field researchers. Modelled
    on real stored supervisors: set theory (Helsinki) and a dermatology
    publication record (the Choudhary case — right institution, wrong work)."""
    for areas, pubs in (
        (["Advanced Topology and Set Theory", "Logic, Reasoning, and Knowledge"],
         [{"title": "Inner models from extended logics"}]),
        ([], [{"title": "Flutamide for hair loss: A systematic review"},
              {"title": "Patient attitudes toward artificial intelligence in dermatology"}]),
    ):
        sup = _good_sup() | {"research_areas": areas, "publications": pubs}
        g = outreach_gate(_profile(), {"university": "Tampere University"}, sup)
        assert not g["checks"]["topical_fit"], (areas, g["topic_similarity"])
        assert not g["allowed"]


def test_rejects_name_with_role_word_suffix():
    """Live artifact: 'Marius Muench Assistant' was scraped from a Birmingham
    staff page and stored as a person (and pattern-guessed an email)."""
    for junk in ("Marius Muench Assistant", "Helen Abnett Lecturer",
                 "John Smith Postdoctoral Fellow"):
        ok, _ = person_name_check(junk)
        assert not ok, junk


def test_gate_blocks_orcid_affiliation_mismatch():
    """Live case: Helen Abnett passed every check for a Birmingham position
    while her ORCID (and public email, @herts.ac.uk) named only the
    University of Hertfordshire — a moved researcher or name collision must
    be forced to manual review, not emailed at the wrong institution."""
    sup = _good_sup()
    sup["metrics"] = {"works_count": 59,
                      "orcid_affiliation_mismatch": ["University of Hertfordshire"]}
    g = outreach_gate(_profile(), {"university": "Tampere University"}, sup)
    assert not g["checks"]["affiliation_consistent"]
    assert not g["allowed"]
    assert any("moved" in r or "collision" in r for r in g["reasons"])


def test_gate_blocks_pattern_guessed_email():
    """A pattern-guessed address must never be treated as verified: even a
    perfectly aligned supervisor is blocked until the user marks the email
    manually verified after checking the official page."""
    sup = _good_sup() | {"email_confidence": "pattern_guess"}
    g = outreach_gate(_profile(), {"university": "Tampere University"}, sup)
    assert g["recipient_email"] == "guessed"
    assert not g["checks"]["recipient_email"]
    assert not g["allowed"]
    # ... and manual verification unblocks it
    sup["email_confidence"] = "manual_verified"
    g2 = outreach_gate(_profile(), {"university": "Tampere University"}, sup)
    assert g2["allowed"] and g2["recipient_email"] == "present"


def test_gate_blocks_missing_email():
    sup = _good_sup() | {"email": ""}
    g = outreach_gate(_profile(), {"university": "Tampere University"}, sup)
    assert g["recipient_email"] == "missing"
    assert not g["allowed"]


def test_generate_email_refuses_junk_supervisor():
    from app.docgen.generators import generate_email
    junk = {"name": "Jean Monnet", "university": "Tampere University",
            "profile_url": "https://www.tuni.fi/en/search?search_type=people"}
    em = generate_email(_profile() | {"name": "Test"}, junk, "any topic",
                        position={"university": "Tampere University"})
    assert em.get("blocked") and em["id"] is None
    assert "Manual review required" in em["warning"]
