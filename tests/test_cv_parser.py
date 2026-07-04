from pathlib import Path

from app.cv_parser import parse_cv

FIXTURE = Path(__file__).parent / "fixtures" / "sample_cv.txt"


def test_parse_sample_cv():
    profile, warnings = parse_cv(FIXTURE)
    assert profile["name"] == "Amina Hassan Yusuf"
    assert profile["email"] == "amina.yusuf@example.org"
    assert any("MBA" in d or "M" in d for d in profile["degrees"])
    assert any("microfinance" in a.lower() or "ngo" in a.lower()
               for a in profile["research_areas"])
    assert len(profile["publications"]) >= 1
    assert "nonprofit" in profile["keywords"] or "microfinance" in profile["keywords"]


def test_parse_garbage_gives_warnings(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("x")
    profile, warnings = parse_cv(bad)
    assert warnings  # warns instead of crashing
    assert profile["name"] == "" or profile["email"] == ""


def test_unsupported_extension(tmp_path):
    weird = tmp_path / "cv.xyz"
    weird.write_text("hello")
    try:
        parse_cv(weird)
        assert False, "should raise"
    except ValueError as e:
        assert "PDF or DOCX" in str(e)
