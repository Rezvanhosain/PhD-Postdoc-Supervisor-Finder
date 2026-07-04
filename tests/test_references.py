from unittest import mock

from app.references import audit_table, format_reference, verify_reference

REF = {
    "title": "Microfinance and its discontents",
    "authors": ["Jane Q Smith", "Robert Jones"],
    "year": "2019", "venue": "World Development",
    "doi": "10.1000/example", "url": "https://doi.org/10.1000/example",
    "source_api": "openalex", "verified": True,
}


def test_format_all_styles_include_core_fields():
    for style in ("APA 7", "Harvard", "Chicago", "IEEE"):
        s = format_reference(REF, style)
        assert "Microfinance" in s
        assert "2019" in s
        assert "10.1000/example" in s


def test_apa_author_formatting():
    s = format_reference(REF, "APA 7")
    assert "Smith, J. Q." in s
    assert "& Jones, R." in s


def test_verify_rejects_untrusted_source_without_doi():
    ref = {"title": "Made up paper", "authors": ["A B"], "doi": "", "source_api": "llm"}
    out = verify_reference(ref)
    assert out["verified"] is False
    assert "manual review" in out["verification_note"].lower()


def test_verify_keeps_api_sourced_ref_without_doi():
    ref = {"title": "Real paper", "authors": ["A B"], "doi": "", "source_api": "openalex"}
    out = verify_reference(ref)
    assert out["verified"] is True


def test_verify_doi_uses_crossref():
    with mock.patch("app.references.crossref.lookup_doi", return_value={"title": "x"}):
        out = verify_reference(dict(REF))
        assert out["verified"] is True
        assert "Crossref" in out["verification_note"]
    with mock.patch("app.references.crossref.lookup_doi", return_value=None):
        out = verify_reference({"title": "y", "authors": ["A"], "doi": "10.1/bad",
                                "source_api": "somewhere"})
        assert out["verified"] is False


def test_audit_table_marks_unverified():
    table = audit_table([REF, {"title": "Suspicious", "verified": False}])
    assert "VERIFIED" in table
    assert "NEEDS MANUAL REVIEW" in table
