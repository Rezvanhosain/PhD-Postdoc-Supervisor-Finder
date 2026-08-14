import pytest

from proposal_engine.bibliography import (CitationGateError, VERIFIED, DOI_UNRESOLVED,
                                          METADATA_MISMATCH, NO_DOI, audit_citations,
                                          build_bibliography)
from proposal_engine.validators import (extract_citation_keys, find_placeholders,
                                        unknown_citation_keys, unsupported_claims,
                                        validate_section)


def test_placeholder_gate():
    assert find_placeholders("all good") == []
    assert find_placeholders("see [FILL IN] and TODO here")


def test_extract_and_unknown_keys():
    text = "Prior work [@smith2020; @lee2019] shows results [@doe2021]."
    assert set(extract_citation_keys(text)) == {"smith2020", "lee2019", "doe2021"}
    assert unknown_citation_keys(text, {"smith2020"}) == ["lee2019", "doe2021"]


def test_unsupported_claim_needs_assumption():
    bad = "We will recruit participants from the national cohort."
    assert unsupported_claims(bad)
    ok = "Assumption: we will recruit participants from a national cohort."
    assert unsupported_claims(ok) == []


def test_validate_section_reports_multiple():
    errs = validate_section("short TODO", 50, {"a"}, require_citation=True)
    assert any("placeholder" in e for e in errs)
    assert any("word floor" in e for e in errs)
    assert any("no in-text citations" in e for e in errs)


EVIDENCE = [
    {"key": "smith2020", "title": "Alpha study", "authors": ["Jane Smith"], "year": 2020,
     "venue": "J", "doi": "10.1/alpha", "abstract": "x", "oa_url": ""},
    {"key": "lee2019", "title": "Beta study", "authors": ["Kim Lee"], "year": 2019,
     "venue": "J", "doi": "", "abstract": "y", "oa_url": "http://oa"},
]


def test_bibliography_only_from_evidence_store():
    draft = "Intro [@smith2020]. More [@lee2019]."
    cited, csl = build_bibliography(draft, EVIDENCE)
    assert {c["id"] for c in csl} == {"smith2020", "lee2019"}
    assert len(cited) == 2


def test_bibliography_gate_rejects_unknown_key():
    with pytest.raises(CitationGateError):
        build_bibliography("Uses [@ghost1999].", EVIDENCE)


def test_bibliography_excludes_uncited():
    cited, csl = build_bibliography("Only [@smith2020] here.", EVIDENCE)
    assert [c["id"] for c in csl] == ["smith2020"]


def test_citation_audit_statuses():
    cited = EVIDENCE  # smith2020 has DOI, lee2019 has none

    def verify(doi):
        if doi == "10.1/alpha":
            return {"title": "Alpha study", "year": "2020"}
        return None

    rows = audit_citations(cited, verify)
    by_key = {r["key"]: r for r in rows}
    assert by_key["smith2020"]["status"] == VERIFIED
    assert by_key["lee2019"]["status"] == NO_DOI


def test_citation_audit_mismatch_and_unresolved():
    cited = [EVIDENCE[0]]

    assert audit_citations(cited, lambda d: None)[0]["status"] == DOI_UNRESOLVED
    mismatch = audit_citations(cited, lambda d: {"title": "Totally different", "year": "1990"})
    assert mismatch[0]["status"] == METADATA_MISMATCH
