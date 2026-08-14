"""Document-sanitization layer (final cleanup before render).

The drafting model occasionally leaks raw Markdown into section prose: ``**bold**``
markers, stray heading marks, inline-crammed lists, and adjacent citation groups
with no separator. This module converts or removes those artifacts so nothing
raw reaches the DOCX/PDF. It is intentionally dependency-free and pure so it can
be unit-tested in isolation and reused by the renderer and the quality gate.

Design rules:
- Never invent content. Cleanup only rewrites markup, never facts.
- Bold markers become structured (segment, bold) runs the renderer can honour;
  when a caller only needs plain text, ``strip_markup`` removes the markers.
- Adjacent citation groups are merged, but valid Pandoc keys ``[@a; @b]`` and
  URLs are left untouched (the fix runs on resolved prose, and is year-guarded).
"""
from __future__ import annotations

import re

# Leading Markdown heading marker on a line, e.g. "## Title" -> "Title".
_HEADING_MARK_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
# A **bold** or __bold__ span (non-greedy, single-line).
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
# Any leftover emphasis/heading markers we must never ship.
_STRAY_MARK_RE = re.compile(r"\*\*|__|^\s{0,3}#{1,6}\s*", re.MULTILINE)
# Two citation groups touching, each containing a 4-digit year:
#   (Duis & Coors, 2016)(Kataoka et al., 2018) -> (Duis & Coors, 2016; Kataoka et al., 2018)
_ADJ_CITE_RE = re.compile(
    r"\(([^()]*?\b\d{4}[a-z]?\b[^()]*?)\)\s*\(([^()]*?\b\d{4}[a-z]?\b[^()]*?)\)"
)


def strip_heading_marks(line: str) -> str:
    """Remove a leading Markdown heading marker from a single line."""
    return _HEADING_MARK_RE.sub("", line)


def bold_segments(text: str) -> list[tuple[str, bool]]:
    """Split ``text`` into ``(segment, is_bold)`` runs, honouring ``**``/``__``.

    Consecutive plain runs are preserved as separate items only where a bold run
    interrupts them; empty segments are dropped. This is what the DOCX builder
    uses to emit real bold runs instead of literal asterisks.
    """
    segments: list[tuple[str, bool]] = []
    pos = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > pos:
            segments.append((text[pos:m.start()], False))
        inner = m.group(1) if m.group(1) is not None else m.group(2)
        if inner:
            segments.append((inner, True))
        pos = m.end()
    if pos < len(text):
        segments.append((text[pos:], False))
    return [(s, b) for s, b in segments if s]


def strip_markup(text: str) -> str:
    """Return plain text with all bold/heading markers removed (no styling)."""
    out = "".join(seg for seg, _ in bold_segments(text))
    out = _STRAY_MARK_RE.sub("", out)
    return out


def fix_adjacent_citations(text: str) -> str:
    """Merge back-to-back citation parentheses into one group.

    ``(A, 2016)(B, 2018)`` and ``(A, 2016) (B, 2018)`` both become
    ``(A, 2016; B, 2018)``. Runs repeatedly so three or more adjacent groups
    collapse. Only groups that each contain a four-digit year are touched, so
    ordinary parentheticals and URLs are left alone.
    """
    prev = None
    cur = text
    while prev != cur:
        prev = cur
        cur = _ADJ_CITE_RE.sub(lambda m: f"({m.group(1).strip()}; {m.group(2).strip()})", cur)
    return cur


def has_markdown_artifacts(text: str) -> bool:
    """True if raw bold/heading markers survive anywhere in ``text``."""
    return bool(_STRAY_MARK_RE.search(text or ""))


def has_adjacent_citations(text: str) -> bool:
    """True if two citation groups are touching with no separator."""
    return bool(_ADJ_CITE_RE.search(text or ""))


def strip_stray_markers(text: str) -> str:
    """Remove leftover bold/heading markers from a plain (already de-bolded)
    fragment without touching its words."""
    return _STRAY_MARK_RE.sub("", text or "")


def normalize_block(text: str) -> str:
    """Light cleanup that KEEPS ``**bold**`` markers for the renderer to convert
    into real bold runs. Strips leading heading marks, merges adjacent citations,
    and collapses runs of spaces."""
    lines = [strip_heading_marks(ln) for ln in (text or "").splitlines()]
    joined = fix_adjacent_citations("\n".join(lines))
    return re.sub(r"[ \t]{2,}", " ", joined).strip()


def clean_prose(text: str) -> str:
    """Full plain-text cleanup for a resolved body block: strip markup and merge
    adjacent citations. Whitespace inside the block is normalised per line."""
    lines = [strip_heading_marks(ln) for ln in (text or "").splitlines()]
    joined = "\n".join(lines)
    joined = strip_markup(joined)
    joined = fix_adjacent_citations(joined)
    # collapse runs of spaces but keep newlines
    joined = re.sub(r"[ \t]{2,}", " ", joined)
    return joined.strip()
