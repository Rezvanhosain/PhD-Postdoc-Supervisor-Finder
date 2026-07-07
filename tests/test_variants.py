"""Variant generation: verified-only references, gate enforcement, no AI-slop."""
import json

from app import variants
from app.db import rows

PROFILE = {"name": "Cand Idate", "email": "cand@example.org", "target_level": "PhD",
           "research_areas": ["international development", "NGO accountability",
                              "civil society"]}

POS = {"id": 1, "title": "PhD in International Development",
       "university": "University of Helsinki", "country": "FI",
       "funding": "fully funded 4 years", "deadline": "2026-09-30",
       "description": "international development NGO accountability civil society"}

SUP = {"id": 1, "name": "Anna Virtanen", "title": "Professor",
       "university": "University of Helsinki",
       "email": "anna.virtanen@helsinki.fi", "email_confidence": "official_page",
       "profile_url": "https://helsinki.fi/people/anna-virtanen",
       "research_areas": json.dumps(["international development", "civil society",
                                     "NGO accountability", "development studies"]),
       "publications": json.dumps([
           {"title": "NGO accountability in East Africa", "year": "2024",
            "venue": "World Development", "verified": True},
           {"title": "Unverified web-scraped thing", "year": "2023", "verified": False}]),
       "metrics": json.dumps({"evidence": ["e1", "e2"]}), "source_type": "official"}


def test_proposal_variants_contain_only_verified_references(monkeypatch):
    fake_refs = [
        {"title": "Good paper", "authors": ["A B"], "year": "2020", "venue": "J",
         "doi": "10.1/x", "source_api": "openalex"},
        {"title": "Sketchy paper", "authors": ["C D"], "year": "2021", "venue": "J",
         "doi": "", "source_api": "some_blog"},
    ]
    monkeypatch.setattr(variants, "collect_verified", lambda t, limit=10: list(fake_refs))
    monkeypatch.setattr(
        variants, "verify_reference",
        lambda r: {**r, "verified": r["source_api"] == "openalex",
                   "verification_note": "test"})
    res = variants.proposal_variants(PROFILE, POS, SUP, "NGO accountability")
    assert res["verified"] == 1 and res["flagged"] == 1
    assert len(res["variants"]) == 3
    for v in res["variants"]:
        joined = " ".join(v["references"])
        assert "Good paper" in joined
        assert "Sketchy paper" not in joined       # unverified never cited
    assert "NEEDS MANUAL REVIEW" in res["audit"]   # ...but appears in the audit
    assert res["variants"][0]["template_fallback"] is True  # no LLM key in tests


def test_email_variants_have_no_banned_phrases_and_are_marked_fallback():
    res = variants.email_variants(PROFILE, POS, SUP)
    assert res["blocked"] is False
    assert len(res["drafts"]) == 3
    kinds = {d["variant"] for d in res["drafts"]}
    assert kinds == {"short_direct", "research_fit", "funding_specific"}
    for d in res["drafts"]:
        assert variants.banned_phrases_in(d["subject"] + " " + d["body"]) == []
        assert d["template_fallback"] is True
        assert "needs human rewrite" in d["note"]
        assert d["id"] > 0
    stored = rows("SELECT * FROM email_log WHERE status='draft' AND supervisor_id=1")
    assert len(stored) >= 3
    # only the verified publication is ever cited
    bodies = " ".join(d["body"] for d in res["drafts"])
    assert "Unverified web-scraped thing" not in bodies


def test_email_variants_blocked_when_gate_blocks():
    sup = dict(SUP)
    sup["email"] = "guess.name@helsinki.fi"
    sup["email_confidence"] = "pattern_guess"
    res = variants.email_variants(PROFILE, POS, sup)
    assert res["blocked"] is True
    assert res["drafts"] == []
    assert "no drafts" in res["warning"].lower() or "BLOCKED" in res["warning"]
