"""Structural parsing for list-like sections and the work-plan timeline.

These are pure functions that turn a section's prose into the structured items
the DOCX builder renders as bullet lists, RQ/H labels, or a Gantt table. Keeping
them here (not in the renderer) makes them unit-testable without python-docx and
keeps rendering reliable regardless of exactly how the model formatted its text.
"""
from __future__ import annotations

import math
import re

# ------------------------------------------------------------------ list items
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+(.*\S)\s*$")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")


def split_bullets(text: str) -> list[str]:
    """Return objective-style items from ``text``.

    Prefers explicit bullet / numbered lines; if the model crammed the items into
    one paragraph, falls back to sentence splitting so objectives still render as
    separate bullets rather than a wall of text.
    """
    items: list[str] = []
    for line in text.splitlines():
        m = _BULLET_LINE_RE.match(line)
        if m:
            items.append(m.group(1).strip())
    if items:
        return items
    # No explicit bullets: split the (single) paragraph into sentences.
    flat = " ".join(text.split())
    if not flat:
        return []
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(flat) if s.strip()]
    return sentences if len(sentences) > 1 else [flat]


def split_labeled(text: str, prefix: str) -> list[str]:
    """Split ``text`` into label-prefixed items (e.g. RQ1, RQ2 or H1, H2).

    Recognises existing ``RQ1:``/``H1:`` style labels (any case, optional dot),
    and otherwise splits into sentences and auto-labels them. Returned strings
    include a normalised ``PREFIXn: ...`` label.
    """
    label_re = re.compile(rf"\b{prefix}\s*(\d+)\s*[:.\)]?\s*", re.IGNORECASE)
    matches = list(label_re.finditer(text))
    items: list[str] = []
    if matches:
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = " ".join(text[start:end].split()).strip(" ;")
            if body:
                items.append(f"{prefix}{int(m.group(1))}: {body}")
        return items
    # No labels present: fall back to bullet/sentence split, then auto-label.
    parts = split_bullets(text)
    return [f"{prefix}{i + 1}: {p}" for i, p in enumerate(parts)]


# ------------------------------------------------------------------ timeline / Gantt
def parse_duration_months(duration: str, default: int = 36) -> int:
    """Parse '36 months' / '3 years' / '48' into a month count."""
    if not duration:
        return default
    m = re.search(r"(\d+)", duration)
    if not m:
        return default
    n = int(m.group(1))
    if re.search(r"year", duration, re.IGNORECASE):
        return n * 12
    return n  # bare number or 'months'


def year_columns(total_months: int) -> list[tuple[str, int, int]]:
    """Return one (label, start_month, end_month) per project year."""
    years = max(1, math.ceil(total_months / 12))
    cols: list[tuple[str, int, int]] = []
    for k in range(years):
        start = k * 12 + 1
        end = min((k + 1) * 12, total_months)
        cols.append((f"Year {k + 1} (M{start}–{end})", start, end))
    return cols


# A timeline bullet the drafter is asked to emit, e.g.
#   "- Systematic literature review (months 1-9)"  or  "(Year 1-2)"
_PHASE_MONTH_RE = re.compile(
    r"months?\s*(\d+)\s*(?:[-–to]+)\s*(\d+)", re.IGNORECASE)
_PHASE_YEAR_RE = re.compile(
    r"years?\s*(\d+)\s*(?:[-–to]+\s*(\d+))?", re.IGNORECASE)
_PHASE_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$")
# A bullet separator that has whitespace on BOTH sides — how a model separates
# phases crammed onto one line ("... review - Development ..."). Intra-word
# hyphens ("privacy-preserving") have no surrounding space and are preserved.
_INLINE_BULLET_RE = re.compile(r"\s+[-–•]\s+")


def _split_inline_bullets(text: str) -> str:
    """Turn inline ' - ' phase separators into their own bullet lines."""
    return _INLINE_BULLET_RE.sub("\n- ", text)


def _clean_phase_name(raw: str) -> str:
    # Drop a trailing "(months 1-9)" / "(Year 1-2)" annotation and separators.
    name = re.split(r"[(—:]|\bmonths?\b|\byears?\b", raw, maxsplit=1, flags=re.IGNORECASE)[0]
    return name.strip(" -–—:;,").strip()


def parse_timeline_phases(text: str, total_months: int) -> list[tuple[str, int, int]]:
    """Extract (phase_name, start_month, end_month) rows from timeline prose.

    Reads bullet lines that carry a "(months A-B)" or "(Year X-Y)" annotation.
    Returns only well-formed rows; the caller decides whether to fall back to
    :func:`default_phases` when too few are found.
    """
    phases = _parse_phase_lines(text, total_months)
    if len(phases) >= 3:
        return phases
    # Fallback: phases crammed onto one line — split inline ' - ' separators
    # into bullet lines and re-parse.
    inline = _parse_phase_lines(_split_inline_bullets(text), total_months)
    return inline if len(inline) >= 3 else phases


def _parse_phase_lines(text: str, total_months: int) -> list[tuple[str, int, int]]:
    phases: list[tuple[str, int, int]] = []
    for line in text.splitlines():
        m = _PHASE_LINE_RE.match(line)
        if not m:
            continue
        body = m.group(1)
        name = _clean_phase_name(body)
        if not name:
            continue
        mm = _PHASE_MONTH_RE.search(body)
        if mm:
            start, end = int(mm.group(1)), int(mm.group(2))
        else:
            ym = _PHASE_YEAR_RE.search(body)
            if not ym:
                continue
            y1 = int(ym.group(1))
            y2 = int(ym.group(2)) if ym.group(2) else y1
            start, end = (y1 - 1) * 12 + 1, y2 * 12
        start = max(1, min(start, total_months))
        end = max(start, min(end, total_months))
        phases.append((name, start, end))
    return phases


def default_phases(total_months: int) -> list[tuple[str, int, int]]:
    """Canonical PhD phases scaled to the project duration.

    Generic and duration-aware (never fabricated topic-specific claims); used
    when the drafted timeline does not enumerate parseable phases.
    """
    spec = [
        ("Systematic literature review and gap consolidation", 0.00, 0.25),
        ("Research design, protocol, and pilot preparation", 0.10, 0.30),
        ("Data collection / pipeline and instrument setup", 0.20, 0.50),
        ("Core method development and implementation", 0.30, 0.65),
        ("Experiments, fieldwork, or model evaluation", 0.45, 0.80),
        ("Analysis, validation, and sensitivity checks", 0.60, 0.88),
        ("Publications, dissemination, and software release", 0.55, 0.95),
        ("Thesis integration, writing, and defence preparation", 0.80, 1.00),
    ]
    rows: list[tuple[str, int, int]] = []
    for name, s, e in spec:
        start = max(1, round(s * total_months) + 1)
        end = max(start, min(round(e * total_months), total_months))
        rows.append((name, start, end))
    return rows


def phase_active_in_year(phase: tuple[str, int, int], col: tuple[str, int, int]) -> bool:
    """True if the phase's month span overlaps this year column."""
    _, ps, pe = phase
    _, cs, ce = col
    return ps <= ce and pe >= cs
