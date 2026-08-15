"""Shared test helpers for proposal_engine tests. No live API calls anywhere."""
from __future__ import annotations

import copy
import re

from proposal_engine.evidence import EvidenceProvider

TOPIC_KEYWORDS = {
    "alpha": ["microplastics", "estuarine", "sediment", "toxicity"],
    "beta": ["federated", "learning", "privacy", "healthcare"],
    "gamma": ["perovskite", "photovoltaic", "stability", "efficiency"],
    "delta": ["obscuretopic", "nichearea"],  # low-evidence topic
}


def _abstract(tag: str, i: int) -> str:
    kws = " ".join(TOPIC_KEYWORDS[tag])
    return (f"This study investigates {kws} in detail. Using established methods, "
            f"experiment {i} reports measurable outcomes relevant to {kws}. "
            "The findings extend prior scholarship and inform future analysis.")


def make_works(tag: str, n: int, with_abstract: bool = True) -> list[dict]:
    works = []
    for i in range(n):
        works.append({
            "title": f"{TOPIC_KEYWORDS[tag][0].title()} investigation {i}: methods and results",
            "authors": [f"Researcher{i} Author{i}", "Second Collaborator"],
            "year": 2016 + (i % 8),
            "venue": "Journal of Reproducible Testing",
            "doi": f"10.1000/{tag}.{i}",
            "abstract": _abstract(tag, i) if with_abstract else "",
            "oa_url": "",
            "cited_by": 5 + i,
            "source_api": "openalex",
            "source_ids": {"openalex": f"https://openalex.org/W{tag}{i}"},
        })
    return works


class FixtureProvider(EvidenceProvider):
    """Returns the same recorded works for any query of its topic."""

    def __init__(self, works: list[dict]):
        self._works = works

    def works(self, query: str, per_page: int) -> list[dict]:
        return copy.deepcopy(self._works[:per_page])


class FakeLLM:
    """Deterministic stand-in for a drafting model. Produces schema-valid JSON
    that satisfies the validators (word floors, citations, no placeholders)."""

    _FILLER = ("The study synthesizes prior findings and situates them within a "
               "coherent analytical frame, clarifying scope and relevance for the "
               "field under consideration. ")

    def generate_json(self, system: str, user: str, max_tokens: int = 2000):
        low = system.lower()
        if "librarian" in low or "search strategy" in low:
            title = ""
            m = re.search(r"Title:\s*(.+)", user)
            if m:
                title = m.group(1).strip()
            base = title or "research topic"
            return {
                "queries": [base, f"{base} systematic review", f"{base} methodology"],
                "inclusion_criteria": ["Peer-reviewed", "English", "Has abstract"],
                "exclusion_criteria": ["Editorials"],
            }
        return {"text": self._section_text(user)}

    def _section_text(self, user: str) -> str:
        name_m = re.search(r"write the '([^']+)' section", user)
        name = name_m.group(1) if name_m else "Section"
        target_m = re.search(r"~(\d+) words", user)
        target = int(target_m.group(1)) if target_m else 150
        keys = []
        for span in re.findall(r"\[@([A-Za-z0-9_:\-]+)\]", user):
            if span not in keys:
                keys.append(span)

        if name.lower() == "title":
            return "An Evidence-Based Investigation of the Research Topic Under Study"

        parts = [f"This {name.lower()} presents a complete, evidence-grounded discussion "
                 "of the research problem and its scholarly context."]
        if keys:
            cited = keys[:2]
            parts.append("Existing scholarship "
                         + " and ".join(f"[@{k}]" for k in cited)
                         + " establishes the analytical foundation for this work.")
        text = " ".join(parts)
        while len(text.split()) < target + 8:
            text += " " + self._FILLER
        return text.strip()
