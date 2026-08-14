"""Deterministic CV de-contamination + topic-fidelity gate tests.

Regression anchor: Arsalan's CV states the proposed direction
"Availability-aware clustered federated continual learning for predictive
maintenance in Industrial IoT edge systems." None of its distinctive terms may
appear in a proposal for topic 001 unless the topic or evidence contains them.
All offline.
"""
from __future__ import annotations

import pytest

from proposal_engine import candidate_context as cc

# A representative slice of the real extracted profile (line-wrapped like the PDF).
ARSALAN = """ARSALAN JAVED
PROFESSIONAL SUMMARY
Computer Science professional with an MS in Computer Science and more than a
decade of experience in public-sector information systems and IT support.
His academic interests include artificial intelligence, machine learning, deep
learning, data science, Industrial IoT, predictive analytics, and federated learning.
He is seeking PhD supervision in a research topic aligned with the prospective
supervisor's current projects and priorities.
RESEARCH PROFILE
Proposed PhD direction: Availability-aware clustered federated continual learning
for predictive maintenance in Industrial IoT edge systems.
MS thesis: Opportunistic Routing with Cooperation in Underwater Sensor Networks.
Research interests: Artificial intelligence, machine learning, Industrial IoT,
predictive analytics, and federated learning.
PROFESSIONAL EXPERIENCE
Assistant Director, International Operations, NADRA, Islamabad, Pakistan.
EDUCATION
Master of Science in Computer Science, CECOS University, Peshawar, Pakistan.
"""

TOPIC_001 = ("Artificial Intelligence, Machine Learning, Data Science, Bayesian "
             "Data Analysis, Federated Learning, and Bioinformatics.")

EXCLUDED = ["predictive maintenance", "industrial iot", "availability-aware",
            "clustered federated continual learning"]


# --------------------------------------------------------------------------- #
# clean_candidate_context: keep facts, drop proposed/preferred-research lines.
# --------------------------------------------------------------------------- #
def test_clean_context_drops_proposed_direction_and_interests():
    cleaned = cc.clean_candidate_context(ARSALAN).lower()
    # Contaminating, forward-looking statements are gone.
    assert "proposed phd direction" not in cleaned
    assert "predictive maintenance" not in cleaned
    assert "industrial iot" not in cleaned
    assert "availability-aware" not in cleaned
    assert "research interests" not in cleaned
    assert "academic interests" not in cleaned


def test_clean_context_keeps_verifiable_candidate_facts():
    cleaned = cc.clean_candidate_context(ARSALAN).lower()
    for fact in ("master of science", "cecos university", "nadra",
                 "professional experience", "ms thesis"):
        assert fact in cleaned, f"candidate fact dropped: {fact}"


# --------------------------------------------------------------------------- #
# direction_terms: the proposed-direction phrases, minus anything in the topic.
# --------------------------------------------------------------------------- #
def test_direction_terms_capture_excluded_direction_for_topic_001():
    terms = cc.direction_terms(ARSALAN, TOPIC_001)
    for t in EXCLUDED:
        assert t in terms, f"missing forbidden term: {t}"
    # 'federated learning' IS in the topic -> must not be treated as forbidden.
    assert "federated learning" not in terms


def test_direction_terms_never_include_generic_academic_phrases():
    # Regression: "research proposal" (from a logistics CV line) and common field
    # phrases must never be forbidden, or ordinary proposal prose would be flagged.
    terms = cc.direction_terms(ARSALAN, TOPIC_001)
    for generic in ("research proposal", "research topic", "machine learning",
                    "deep learning", "continual learning", "data science",
                    "computer vision"):
        assert generic not in terms
    # A normal sentence using those phrases is clean.
    prose = ("This research proposal applies deep learning and continual learning "
             "to computer vision and data science problems.")
    assert cc.find_contamination(prose, terms, TOPIC_001, "") == []


def test_direction_terms_respect_a_topic_that_contains_them():
    # If the user's topic is actually about predictive maintenance in IIoT,
    # those terms are legitimate and must NOT be forbidden.
    on_topic = "Predictive Maintenance for Industrial IoT using Federated Learning"
    terms = cc.direction_terms(ARSALAN, on_topic)
    assert "predictive maintenance" not in terms
    assert "industrial iot" not in terms


# --------------------------------------------------------------------------- #
# find_contamination: flags leaked terms; allows topic/evidence-supported ones.
# --------------------------------------------------------------------------- #
def test_contamination_flags_leaked_terms_absent_from_topic_and_evidence():
    forbidden = cc.direction_terms(ARSALAN, TOPIC_001)
    leaked_text = ("This proposal develops predictive maintenance methods for "
                   "Industrial IoT edge systems.")
    hits = cc.find_contamination(leaked_text, forbidden, TOPIC_001, evidence_text="")
    assert "predictive maintenance" in hits
    assert "industrial iot" in hits


def test_contamination_allows_terms_supported_by_evidence():
    forbidden = cc.direction_terms(ARSALAN, TOPIC_001)
    text = "We reference predictive maintenance only where the literature does."
    evidence = "A survey of predictive maintenance in manufacturing (2021)."
    hits = cc.find_contamination(text, forbidden, TOPIC_001, evidence_text=evidence)
    assert "predictive maintenance" not in hits  # supported by evidence -> allowed


def test_clean_bioinformatics_text_has_no_contamination():
    forbidden = cc.direction_terms(ARSALAN, TOPIC_001)
    clean = ("This proposal integrates federated learning and Bayesian data "
             "analysis for bioinformatics, focusing on privacy-preserving models "
             "for genomic and clinical data.")
    assert cc.find_contamination(clean, forbidden, TOPIC_001, evidence_text="") == []


# --------------------------------------------------------------------------- #
# The explicit regression the task asks for.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("term", EXCLUDED)
def test_topic_001_forbids_each_excluded_direction_term(term):
    forbidden = cc.direction_terms(ARSALAN, TOPIC_001)
    # Each excluded term is recognised as forbidden for topic 001 ...
    assert term in forbidden
    # ... and a draft containing it (with no topic/evidence support) is caught
    # (multi-word terms also surface their overlapping sub-phrases — all genuine).
    assert term in cc.find_contamination(f"... {term} ...", forbidden, TOPIC_001, "")
