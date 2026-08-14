"""Deterministic candidate-context extraction and topic-fidelity checking.

The extracted CV can state the candidate's *own* proposed PhD direction / topic
(e.g. Arsalan's "Availability-aware clustered federated continual learning for
predictive maintenance in Industrial IoT edge systems"). Feeding that verbatim
to the drafter contaminates the proposal, which must follow the user-entered
topic instead. This module:

  * ``clean_candidate_context`` — keep verifiable candidate facts (education,
    employment, skills, research experience, publications) and drop sentences
    that state a *proposed / preferred future* research direction, topic, title,
    or a prior proposal's objectives/questions.
  * ``direction_terms`` — extract the distinctive multi-word terms of the
    *proposed research direction* the candidate stated, minus anything the
    user's topic already contains. These are the terms that must not leak.
  * ``find_contamination`` — report which of those terms appear in drafted text
    while being absent from BOTH the entered topic and the evidence store.

Everything here is pure/deterministic — no LLM, no network.
"""
from __future__ import annotations

import re

# Sentences whose presence marks a *proposed/preferred future* research
# statement — removed from the drafting context entirely.
_EXCLUDE_MARKERS = (
    "proposed phd direction",
    "proposed research direction",
    "proposed research topic",
    "proposed research title",
    "proposed research",
    "proposed direction",
    "proposed topic",
    "proposed title",
    "proposed study",
    "proposed phd",
    "research interests",
    "research interest",
    "academic interests",
    "academic interest",
    "interests include",
    "future research",
    "intended research",
    "planned research",
    "preferred research",
    "seeking phd supervision",
    "seeking supervision",
    "phd supervision in a research topic",
    "research topic aligned",
    "alternative phd topics",
    "phd topic",
    "proposal objectives",
    "research questions",
)

# The narrow subset that specifically states a proposed research *direction /
# topic / title* (or a prior proposal). Only these seed the forbidden terms —
# generic interest lists do not, so ordinary field words are never blocked.
# NOTE: deliberately excludes bare "research proposal" — it also matches logistic
# lines like "certificates and research proposal are available", and the phrase
# itself is ordinary proposal prose.
_DIRECTION_MARKERS = (
    "proposed phd direction",
    "proposed research direction",
    "proposed research topic",
    "proposed research title",
    "proposed research",
    "proposed direction",
    "proposed topic",
    "proposed title",
    "proposed study",
    "proposal objectives",
)

# Generic academic / field phrases that must NEVER be treated as forbidden
# terms, even if they occur in a proposed-direction sentence — otherwise normal
# proposal prose would be falsely flagged as CV contamination.
_GENERIC_TERMS = frozenset({
    "research proposal", "research proposals", "research topic", "research topics",
    "research title", "research direction", "research directions",
    "research question", "research questions", "research interest",
    "research interests", "research aim", "research aims", "research profile",
    "research experience", "future research", "phd research", "phd direction",
    "phd supervision", "proposed direction", "proposed research",
    "academic interests", "professional summary",
    "machine learning", "deep learning", "data science", "data analysis",
    "artificial intelligence", "natural language", "language processing",
    "computer vision", "computer science", "predictive analytics",
    "federated learning", "neural networks", "continual learning",
})

# Connector / function words: segment boundaries so we never build phrases that
# bridge across them, and never treat them as content tokens.
_STOP = {
    "a", "an", "the", "and", "or", "for", "in", "on", "of", "to", "with", "via",
    "using", "based", "within", "across", "into", "at", "by", "as", "is", "are",
    "that", "this", "these", "those", "from", "such", "which",
}
_SEG_RE = re.compile(
    r"\s*[.,;:/()\[\]]\s*|\s+(?:" + "|".join(sorted(_STOP, key=len, reverse=True)) + r")\s+"
)
_HYPHEN_RE = re.compile(r"\b[a-z]+(?:-[a-z]+)+\b")
_WORD_RE = re.compile(r"[a-z0-9]+")


def _sentences(text: str) -> list[str]:
    """Split raw (possibly line-wrapped) profile text into sentences."""
    norm = re.sub(r"[ \t]+", " ", (text or "").replace("\r", ""))
    norm = re.sub(r"\n{2,}", " \x00 ", norm)  # paragraph breaks -> hard boundary
    norm = norm.replace("\n", " ")
    parts = re.split(r"(?<=[.!?])\s+|\x00", norm)
    return [p.strip() for p in parts if p.strip()]


def clean_candidate_context(profile_text: str) -> str:
    """Return the candidate facts with proposed/preferred-research sentences removed."""
    kept = [s for s in _sentences(profile_text)
            if not any(m in s.lower() for m in _EXCLUDE_MARKERS)]
    return " ".join(kept).strip()


def excluded_sentences(profile_text: str) -> list[str]:
    """Sentences that were dropped from the candidate context (for auditing)."""
    return [s for s in _sentences(profile_text)
            if any(m in s.lower() for m in _EXCLUDE_MARKERS)]


def _phrases(segment_source: str) -> set[str]:
    """Distinctive terms of one direction statement: hyphenated tokens plus
    2–4 word content n-grams that do not bridge connector words/punctuation."""
    low = segment_source.lower()
    terms: set[str] = set(_HYPHEN_RE.findall(low))
    for seg in _SEG_RE.split(low):
        toks = [t for t in _WORD_RE.findall(seg) if t not in _STOP]
        for n in (2, 3, 4):
            for i in range(len(toks) - n + 1):
                terms.add(" ".join(toks[i:i + n]))
    return terms


def direction_terms(profile_text: str, topic_text: str) -> list[str]:
    """Distinctive terms of the candidate's stated proposed research direction,
    excluding anything already present in the user's topic."""
    topic_low = (topic_text or "").lower()
    terms: set[str] = set()
    for s in _sentences(profile_text):
        low = s.lower()
        if not any(m in low for m in _DIRECTION_MARKERS):
            continue
        payload = s.split(":", 1)[1] if ":" in s else s  # drop the label prefix
        terms |= _phrases(payload)
    # Keep only distinctive terms: not generic academic phrases and not already
    # covered by the user's topic.
    return sorted(t for t in terms
                  if t and t not in _GENERIC_TERMS and t not in topic_low)


def evidence_blob(evidence: list[dict]) -> str:
    """Lowercased title+abstract+relevance text of the evidence store."""
    out = []
    for e in evidence or []:
        out.append(str(e.get("title", "")))
        out.append(str(e.get("abstract", "")))
        out.append(str(e.get("relevance_note", "")))
    return " ".join(out).lower()


def find_contamination(text: str, forbidden_terms, topic_text: str,
                       evidence_text: str) -> list[str]:
    """Forbidden direction terms present in ``text`` yet absent from both the
    entered topic and the evidence store (i.e. genuine CV contamination)."""
    low = (text or "").lower()
    topic_low = (topic_text or "").lower()
    ev_low = (evidence_text or "").lower()
    hits = [t for t in forbidden_terms
            if t in low and t not in topic_low and t not in ev_low]
    return sorted(set(hits))


def write_candidate_context(cleaned: str, forbidden_terms, out_path) -> None:
    """Persist the cleaned candidate context (auditing artifact)."""
    from pathlib import Path

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Candidate Context (used for drafting)\n",
             "> Verifiable candidate facts only. Statements describing a proposed / "
             "preferred future research direction, topic, or title were removed so "
             "the proposal follows the entered topic, not the CV's stated direction.\n"]
    if forbidden_terms:
        lines.append("\n<!-- excluded direction terms (must not appear unless in the "
                     "topic or evidence): " + "; ".join(forbidden_terms) + " -->\n")
    lines.append("\n" + (cleaned or "*(no candidate facts extracted)*") + "\n")
    out.write_text("".join(lines), encoding="utf-8")
