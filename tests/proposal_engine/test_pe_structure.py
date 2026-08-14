"""Tests for list/label/timeline structural parsing."""
from proposal_engine.structure import (default_phases, parse_duration_months,
                                        parse_timeline_phases,
                                        phase_active_in_year, split_bullets,
                                        split_labeled, year_columns)


def test_split_bullets_from_markers():
    text = "- To identify sources\n- To assess toxicity\n- To evaluate risk"
    items = split_bullets(text)
    assert items == ["To identify sources", "To assess toxicity", "To evaluate risk"]


def test_split_bullets_from_paragraph_fallback():
    text = "To identify sources. To assess toxicity. To evaluate risk."
    items = split_bullets(text)
    assert len(items) == 3
    assert items[0].startswith("To identify")


def test_split_labeled_existing_rq():
    text = "RQ1: How does X vary? RQ2: Does Y improve Z?"
    items = split_labeled(text, "RQ")
    assert items[0].startswith("RQ1:") and "How does X" in items[0]
    assert items[1].startswith("RQ2:")


def test_split_labeled_auto_labels():
    text = "First hypothesis holds. Second hypothesis also holds."
    items = split_labeled(text, "H")
    assert items[0].startswith("H1:")
    assert items[1].startswith("H2:")


def test_parse_duration_months():
    assert parse_duration_months("36 months") == 36
    assert parse_duration_months("3 years") == 36
    assert parse_duration_months("48") == 48
    assert parse_duration_months("") == 36


def test_year_columns_48_months():
    cols = year_columns(48)
    assert len(cols) == 4
    assert cols[0][0].startswith("Year 1")
    assert cols[-1][2] == 48


def test_year_columns_42_months_partial_last():
    cols = year_columns(42)
    assert len(cols) == 4
    assert cols[-1][1] == 37 and cols[-1][2] == 42


def test_parse_timeline_phases_months():
    text = ("A framing sentence.\n"
            "- Systematic literature review (months 1-9)\n"
            "- Method development (months 10-24)\n"
            "- Evaluation and writing (months 25-48)")
    phases = parse_timeline_phases(text, 48)
    assert len(phases) == 3
    assert phases[0][0].startswith("Systematic literature review")
    assert phases[0][1] == 1 and phases[0][2] == 9
    assert phases[2][2] == 48


def test_parse_timeline_phases_inline_one_line():
    # Model crammed all phases onto one line with " - " separators.
    text = ("The timeline is structured as follows. "
            "- Literature review (months 1-6) "
            "- Method development (months 7-18) "
            "- Evaluation and writing (months 19-48)")
    phases = parse_timeline_phases(text, 48)
    assert len(phases) == 3
    assert phases[0][0].startswith("Literature review")
    assert phases[0][1] == 1 and phases[0][2] == 6
    assert phases[2][2] == 48


def test_parse_timeline_phases_years():
    text = "- Fieldwork (Year 1-2)\n- Analysis (Year 3)"
    phases = parse_timeline_phases(text, 48)
    assert phases[0][1] == 1 and phases[0][2] == 24
    assert phases[1][1] == 25 and phases[1][2] == 36


def test_default_phases_scaled():
    phases = default_phases(48)
    assert len(phases) == 8
    assert all(1 <= s <= e <= 48 for _, s, e in phases)
    assert phases[-1][0].lower().startswith("thesis")


def test_phase_active_in_year():
    col = ("Year 2 (M13–24)", 13, 24)
    assert phase_active_in_year(("X", 10, 20), col) is True
    assert phase_active_in_year(("X", 25, 36), col) is False
