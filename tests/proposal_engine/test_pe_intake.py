from proposal_engine.intake import extract_profile, write_profile_md


def test_good_profile_passes(tmp_path):
    p = tmp_path / "cv.txt"
    p.write_text("Jane Researcher\n\n" + ("Experienced scientist. " * 40), encoding="utf-8")
    r = extract_profile(p)
    assert r.ok is True and r.reasons == []


def test_short_profile_flagged(tmp_path):
    p = tmp_path / "cv.md"
    p.write_text("too short", encoding="utf-8")
    r = extract_profile(p)
    assert r.ok is False
    assert any("short" in x for x in r.reasons)


def test_write_profile_md_marks_review(tmp_path):
    p = tmp_path / "cv.txt"
    p.write_text("x", encoding="utf-8")
    r = extract_profile(p)
    out = write_profile_md(r, tmp_path / "extracted_profile.md")
    assert "NEEDS_PROFILE_REVIEW" in out.read_text(encoding="utf-8")


def test_unsupported_format(tmp_path):
    p = tmp_path / "cv.rtf"
    p.write_text("data", encoding="utf-8")
    r = extract_profile(p)
    assert r.ok is False
