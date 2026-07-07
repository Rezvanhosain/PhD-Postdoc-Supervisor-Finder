"""Field-relevance scorer: it must let the candidate's real discipline
through and reject roles that are only lexically similar (the engineering,
math and quantum positions that dominated earlier live runs)."""
from __future__ import annotations

from app.field import field_relevance


def test_accepts_candidate_field_roles():
    for pos in (
        {"title": "Doctoral Researcher in Microfinance and Financial Inclusion",
         "description": "NGO accountability in East Africa"},
        {"title": "PhD in Development Studies",
         "description": "social policy, poverty, nonprofit governance"},
        {"title": "Researcher in Public Administration",
         "description": "civil society and social protection"},
    ):
        r = field_relevance(pos)
        assert r["relevant"], (pos["title"], r)


def test_rejects_unrelated_technical_roles():
    for pos in (
        {"title": "Doctoral Researcher in Dependable Automation, Artificial "
                  "Intelligence and Machine Learning",
         "description": "robotics, software, algorithms"},
        {"title": "Doctoral Researcher in Set Theory and Mathematical Logic",
         "description": "topology and algebra"},
        {"title": "Postdoc in Quantum Optomechanics with Polaritons",
         "description": "photonics, semiconductor"},
        {"title": "Coordination and Strategic Program Management",
         "description": "remote sensing biomass earth system"},
    ):
        r = field_relevance(pos)
        assert not r["relevant"], (pos["title"], r)


def test_stray_positive_word_does_not_pass_technical_role():
    # "program management" of a physics lab must not pass on 'management' alone
    r = field_relevance({"title": "Program Management of Quantum Photonics Lab",
                         "description": "semiconductor lasers, deep learning"})
    assert not r["relevant"]


def test_employer_descriptor_nonprofit_does_not_pass():
    """Live false positives: the employer being 'a non-profit organisation'
    is not field signal (cybersecurity engineer at a nonprofit tech centre,
    physics PhD at the non-profit European XFEL)."""
    for pos in (
        {"title": "Principal Research Engineer in Applied Cybersecurity",
         "description": "Funditec is a nonprofit technology centre"},
        {"title": "PhD Student for High-field THz Sources and THz Science",
         "description": "European XFEL is a non-profit research organisation; photonics"},
        {"title": "Head of Prospect Development",
         "description": "philanthropy fundraising for the university"},
    ):
        r = field_relevance(pos)
        assert not r["relevant"], (pos["title"], r)


def test_empty_is_not_relevant():
    assert not field_relevance({})["relevant"]
