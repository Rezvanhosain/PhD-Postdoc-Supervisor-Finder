"""Tests for the document-sanitization layer."""
from proposal_engine.sanitize import (bold_segments, clean_prose,
                                       fix_adjacent_citations,
                                       has_adjacent_citations,
                                       has_markdown_artifacts, strip_heading_marks,
                                       strip_markup)


def test_bold_segments_splits_runs():
    segs = bold_segments("plain **bold** more __also__ end")
    assert ("plain ", False) in segs
    assert ("bold", True) in segs
    assert ("also", True) in segs
    assert all("*" not in s and "_" not in s for s, _ in segs)


def test_strip_markup_removes_all_markers():
    out = strip_markup("A **strong** claim and __double__ and stray ** left")
    assert "**" not in out and "__" not in out
    assert "strong" in out and "double" in out


def test_strip_heading_marks():
    assert strip_heading_marks("## Methodology") == "Methodology"
    assert strip_heading_marks("### 3. Design") == "3. Design"
    assert strip_heading_marks("no heading") == "no heading"


def test_fix_adjacent_citations_merges():
    out = fix_adjacent_citations("(Duis & Coors, 2016)(Kataoka et al., 2018)")
    assert out == "(Duis & Coors, 2016; Kataoka et al., 2018)"


def test_fix_adjacent_citations_with_space():
    out = fix_adjacent_citations("text (Smith, 2020) (Jones, 2021) end")
    assert "(Smith, 2020; Jones, 2021)" in out


def test_fix_adjacent_citations_three_in_a_row():
    out = fix_adjacent_citations("(A, 2016)(B, 2017)(C, 2018)")
    assert out == "(A, 2016; B, 2017; C, 2018)"


def test_fix_adjacent_citations_leaves_non_citations():
    # No 4-digit year -> ordinary parentheses are untouched.
    txt = "the model (baseline)(variant) was tested"
    assert fix_adjacent_citations(txt) == txt


def test_does_not_break_pandoc_keys():
    # Pandoc multi-keys are single brackets and must be preserved verbatim.
    txt = "supported by evidence [@a2020; @b2021]."
    assert fix_adjacent_citations(txt) == txt
    assert not has_adjacent_citations(txt)


def test_has_markdown_artifacts_detects():
    assert has_markdown_artifacts("this is **bold**")
    assert has_markdown_artifacts("## heading")
    assert not has_markdown_artifacts("clean prose (Smith, 2020).")


def test_clean_prose_end_to_end():
    raw = "## Aim\nWe test **X** and cite (A, 2016)(B, 2018)."
    out = clean_prose(raw)
    assert "**" not in out and "#" not in out
    assert "(A, 2016; B, 2018)" in out
    assert out.startswith("Aim") or "Aim" in out
