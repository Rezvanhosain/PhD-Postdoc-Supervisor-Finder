"""Content validators shared by drafting (Stage 4) and the review stage.

No silent fallbacks: these return explicit findings the caller must act on.
"""
from __future__ import annotations

import re

# Placeholder / TODO markers that must never appear in a finished proposal.
PLACEHOLDER_RE = re.compile(r"\[FILL IN|\bTODO\b|\[INSERT|XXX|\[UNVERIFIED", re.IGNORECASE)

# In-text citation keys, e.g. [@smith2020] or [@a2020; @b2021].
_CITE_TOKEN_RE = re.compile(r"@([A-Za-z0-9_:\-]+)")
_CITE_SPAN_RE = re.compile(r"\[[^\]]*@[^\]]+\]")

# High-signal resource/data/access claim patterns. A sentence matching one of
# these must be hedged with an "Assumption:" prefix unless it is clearly past
# tense / evidence-grounded. Kept conservative to avoid false positives.
_CLAIM_PATTERNS = [
    r"\bwe will (?:use|collect|recruit|access|deploy|obtain|analy[sz]e using)\b",
    r"\baccess to the .{0,40}\b(?:dataset|database|cohort|registry|archive|corpus)\b",
    r"\bparticipants will be recruited\b",
    r"\bthe (?:lab|laboratory|institution|university|department) will provide\b",
    r"\bour (?:lab|laboratory|team|institution) (?:has|will)\b",
]
_CLAIM_RE = re.compile("|".join(_CLAIM_PATTERNS), re.IGNORECASE)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def find_placeholders(text: str) -> list[str]:
    return [m.group(0) for m in PLACEHOLDER_RE.finditer(text or "")]


def extract_citation_keys(text: str) -> list[str]:
    """All citation keys referenced in bracketed [@...] spans, de-duplicated."""
    keys: list[str] = []
    for span in _CITE_SPAN_RE.findall(text or ""):
        for k in _CITE_TOKEN_RE.findall(span):
            if k not in keys:
                keys.append(k)
    return keys


def unknown_citation_keys(text: str, valid_keys: set[str]) -> list[str]:
    return [k for k in extract_citation_keys(text) if k not in valid_keys]


def word_count(text: str) -> int:
    return len((text or "").split())


def unsupported_claims(text: str) -> list[str]:
    """Sentences that assert future resources/data/access without an
    'Assumption:' hedge. Returns the offending sentences."""
    findings: list[str] = []
    for sentence in _SENT_SPLIT_RE.split(text or ""):
        s = sentence.strip()
        if not s:
            continue
        if _CLAIM_RE.search(s) and "assumption:" not in s.lower():
            findings.append(s)
    return findings


def validate_section(text: str, word_floor: int, valid_keys: set[str],
                     require_citation: bool = True) -> list[str]:
    """Return a list of human-readable validation errors ([] means valid)."""
    errors: list[str] = []
    ph = find_placeholders(text)
    if ph:
        errors.append(f"placeholder markers present: {sorted(set(ph))}")
    unknown = unknown_citation_keys(text, valid_keys)
    if unknown:
        errors.append(f"citation keys not in evidence_store: {unknown}")
    wc = word_count(text)
    if word_floor > 0 and wc < word_floor:
        errors.append(f"below word floor: {wc} < {word_floor}")
    claims = unsupported_claims(text)
    if claims:
        errors.append("unlabelled resource/access claims (prefix with 'Assumption:'): "
                      + " | ".join(c[:120] for c in claims))
    if require_citation and not extract_citation_keys(text):
        errors.append("no in-text citations [@key] present")
    return errors
