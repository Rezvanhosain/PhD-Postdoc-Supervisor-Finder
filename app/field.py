"""Field-relevance scoring (workflow step 3b, runs BEFORE supervisor search).

The opportunity sources are broad boards: a query for "development" also
returns software-developer, sport-development and macro-finance roles. Before
we spend supervisor-discovery budget on a position, we score how well it fits
*this candidate's actual field* (development / nonprofit / social & public
policy), and reject roles that are only lexically similar (engineering, pure
math, quantum, program-management-of-something-unrelated).

The scorer is deliberately transparent — a curated weighted vocabulary, not a
black box — so every accept/reject decision is explainable in the UI."""
from __future__ import annotations

import re

# Core field vocabulary. Multi-word phrases are matched as phrases (stronger
# signal); single tokens match on word boundaries. Weights reflect how
# diagnostic each term is of the candidate's field.
_POSITIVE: dict[str, float] = {
    "microfinance": 3.0, "micro-finance": 3.0, "microcredit": 3.0,
    # bare "nonprofit"/"non-profit" often describes the EMPLOYER ("a non-profit
    # research organisation"), not the research topic — alone it must not clear
    # MIN_POSITIVE_WEIGHT; the topical phrases below carry the real signal.
    "ngo": 2.0, "non-governmental": 2.0, "nonprofit": 1.5, "non-profit": 1.5,
    "third sector": 2.5, "civil society": 2.0, "philanthropy": 2.0,
    "accountability": 2.0, "governance": 1.5, "nonprofit governance": 3.0,
    "nonprofit management": 3.0, "development studies": 3.0,
    "international development": 3.0, "development economics": 2.5,
    "global development": 2.5, "social policy": 3.0, "public policy": 2.5,
    "public administration": 2.5, "social protection": 2.5,
    "poverty": 2.0, "inequality": 1.5, "financial inclusion": 3.0,
    "impact evaluation": 2.0, "social entrepreneurship": 2.5,
    "humanitarian": 1.5, "aid effectiveness": 2.5, "grassroots": 1.5,
    "capacity building": 1.5, "sustainable development": 1.5,
    "social accounting": 2.5, "corporate social responsibility": 2.0,
    "csr": 1.5, "management": 1.0, "business administration": 1.5,
    "organisational": 1.0, "organizational": 1.0, "social sciences": 1.0,
    "east africa": 1.5, "sub-saharan": 1.5, "global south": 1.5,
    "development finance": 3.0, "community development": 2.5,
}

# Terms that mark a role as belonging to an unrelated technical field. If a
# position is dominated by these and has little positive signal, it is
# rejected even when a stray positive word ("development", "management")
# appears (e.g. "software development", "program management" of a physics lab).
_NEGATIVE: dict[str, float] = {
    "machine learning": 3.0, "artificial intelligence": 3.0, "deep learning": 3.0,
    "quantum": 3.0, "photonics": 3.0, "semiconductor": 3.0, "robotics": 2.5,
    "automation": 2.0, "software": 2.0, "algorithm": 2.0, "computational": 1.5,
    "mathematical logic": 3.0, "set theory": 3.0, "algebra": 3.0, "topology": 3.0,
    "fracture mechanics": 3.0, "materials science": 2.5, "chemistry": 2.5,
    "biochemistry": 2.5, "genomics": 3.0, "molecular": 2.5, "immunology": 3.0,
    "physics": 2.5, "astrophysics": 3.0, "particle": 2.0, "catalyst": 2.5,
    "biomass": 2.5, "remote sensing": 2.0, "wireless": 2.5, "6g": 2.5,
    "neuromorphic": 3.0, "optomechanics": 3.0, "biomarker": 2.5,
    "electrical engineering": 2.5, "mechanical engineering": 2.5,
    "railway": 2.5, "geoscience": 2.0, "earth system": 2.0,
    "cybersecurity": 3.0, "cyber security": 3.0, "research engineer": 2.5,
    # fundraising-office roles ("Prospect Development", "Head of Philanthropy")
    # are jobs at universities, not research positions in the field
    "prospect development": 3.0, "fundraising": 3.0, "alumni relations": 3.0,
}

RELEVANCE_THRESHOLD = 0.28  # normalised positive share required to proceed
# Absolute floor: a single low-weight generic term ("management", "social
# sciences") must not qualify a role on its own. 2.0 = one diagnostic term
# (microfinance, development studies) or two weaker field terms together.
MIN_POSITIVE_WEIGHT = 2.0

# Representative search phrases for this candidate's field, fed to the
# opportunity sources so the discipline is actually surfaced on broad boards.
FIELD_QUERIES = [
    "microfinance", "financial inclusion", "development studies",
    "international development", "nonprofit management", "NGO accountability",
    "social policy", "public policy", "public administration",
    "development finance", "social protection", "civil society",
]


def _count(text: str, vocab: dict[str, float]) -> tuple[float, list[str]]:
    total = 0.0
    hits: list[str] = []
    for term, w in vocab.items():
        if " " in term or "-" in term:
            if term in text:
                total += w
                hits.append(term)
        else:
            if re.search(rf"\b{re.escape(term)}\b", text):
                total += w
                hits.append(term)
    return total, hits


def field_relevance(pos: dict) -> dict:
    """Score one opportunity against the candidate field taxonomy.

    Returns {relevant, score (0..1), matched, against, verdict}. `score` is
    the positive weight's share of (positive + negative) weight, so a role
    heavy in engineering terms scores low even if it contains 'management'."""
    text = " ".join(filter(None, [
        pos.get("title", ""), pos.get("department", ""),
        pos.get("field", ""), pos.get("description", ""),
        pos.get("eligibility", "")])).lower()
    if not text.strip():
        return {"relevant": False, "score": 0.0, "matched": [], "against": [],
                "verdict": "no text to assess"}
    pos_w, pos_hits = _count(text, _POSITIVE)
    neg_w, neg_hits = _count(text, _NEGATIVE)
    denom = pos_w + neg_w
    score = pos_w / denom if denom else 0.0
    # Relevant requires BOTH: enough absolute field signal (not one stray
    # generic word) AND that signal dominating any unrelated-technical signal.
    relevant = pos_w >= MIN_POSITIVE_WEIGHT and score >= RELEVANCE_THRESHOLD
    if pos_w == 0:
        verdict = "no field vocabulary present — outside candidate's field"
    elif pos_w < MIN_POSITIVE_WEIGHT:
        verdict = (f"only weak/generic field terms ({', '.join(pos_hits[:4])}) — "
                   f"not enough field signal to commit supervisor search")
    elif not relevant:
        verdict = (f"dominated by unrelated technical terms "
                   f"({', '.join(neg_hits[:4])}) — weak field fit")
    else:
        verdict = f"field-aligned via {', '.join(pos_hits[:5])}"
    return {"relevant": relevant, "score": round(score, 3),
            "matched": pos_hits, "against": neg_hits, "verdict": verdict}
