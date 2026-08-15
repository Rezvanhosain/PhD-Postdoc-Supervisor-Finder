"""Topic-level draft-retry reliability (Stage 4).

A drafting failure that is a transient (a citation-only miss — a hallucinated key
or a required section with no [@key] — or a malformed/truncated JSON draw) is
usually just LLM variance, so the pipeline redraws the whole topic up to
DRAFT_REDRAFT_RETRIES times before failing closed. Any substantive validation
failure (word floor, placeholders, resource claims, contamination) fails
immediately, and a persistent transient still fails closed — validation is never
loosened. All offline.
"""
from __future__ import annotations

import json

import proposal_engine.draft as drafting
import proposal_engine.render as render_mod
from proposal_engine.config import EngineConfig
from proposal_engine.draft import (DraftingFailed, is_citation_failure,
                                    is_retryable_draft_failure)
from proposal_engine.pipeline import DRAFT_REDRAFT_RETRIES, run_topic
from proposal_engine.render import RenderPDFUnavailable
from proposal_engine.topics import Topic

from _helpers import FixtureProvider, make_works

BETA = Topic(id="beta", title="Federated learning privacy healthcare", keywords=["federated"])
_WORKS = make_works("beta", 15)
_DOI_MAP = {w["doi"]: {"title": w["title"], "year": str(w["year"])} for w in _WORKS}


def _verify(doi):
    return _DOI_MAP.get(doi)


def _no_pdf(*a, **k):
    raise RenderPDFUnavailable("simulated: no PDF engine on this machine")


def _cfg():
    return EngineConfig(evidence_minimum=12, discipline="Science")


# --------------------------------------------------------------------------- #
# Unit: the citation-failure classifier drives the retry decision.
# --------------------------------------------------------------------------- #
def test_is_citation_failure_true_for_citation_only_errors():
    assert is_citation_failure(DraftingFailed("methodology",
        ["no in-text citations [@key] present"]))
    assert is_citation_failure(DraftingFailed("sampling",
        ["citation keys not in evidence_store: ['jian2020']"]))


def test_is_citation_failure_false_for_non_citation_or_mixed():
    # word-floor only -> not a citation problem
    assert not is_citation_failure(DraftingFailed("aim", ["below word floor: 10 < 75"]))
    # contamination only -> fail closed, do not retry
    assert not is_citation_failure(DraftingFailed("aim",
        ["off-topic terms from the candidate's own proposed/prior research "
         "direction appear ... : predictive maintenance"]))
    # mixed (citation + something else) -> not "only" citation -> False
    assert not is_citation_failure(DraftingFailed("methodology",
        ["no in-text citations [@key] present", "below word floor: 10 < 75"]))
    # no recorded errors -> False
    assert not is_citation_failure(DraftingFailed("aim", []))


def test_is_retryable_draft_failure_covers_citation_and_transient_json():
    # citation-only and transient malformed-JSON draws are both retryable
    assert is_retryable_draft_failure(DraftingFailed("methodology",
        ["no in-text citations [@key] present"]))
    assert is_retryable_draft_failure(DraftingFailed("research_gap",
        ["invalid JSON output: could not parse JSON from model response: '{\"text\": \"..."]))
    # a citation miss AND a transient in the same failure is still retryable
    assert is_retryable_draft_failure(DraftingFailed("methodology",
        ["no in-text citations [@key] present", "invalid JSON output: boom"]))


def test_is_retryable_draft_failure_false_for_substantive_errors():
    assert not is_retryable_draft_failure(DraftingFailed("aim", ["below word floor: 10 < 75"]))
    assert not is_retryable_draft_failure(DraftingFailed("aim",
        ["placeholder markers present: ['TODO']"]))
    # transient mixed with a substantive error -> fail closed (not all retryable)
    assert not is_retryable_draft_failure(DraftingFailed("methodology",
        ["invalid JSON output: boom", "below word floor: 10 < 75"]))
    assert not is_retryable_draft_failure(DraftingFailed("aim", []))


def _flaky_draft(monkeypatch, *, fail_times: int, errors: list[str]):
    """Patch draft_proposal to raise DraftingFailed(errors) the first ``fail_times``
    calls, then delegate to the real drafter. Returns a call counter."""
    calls = {"n": 0}
    real = drafting.draft_proposal

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise DraftingFailed("methodology", list(errors))
        return real(*a, **k)

    monkeypatch.setattr(drafting, "draft_proposal", flaky)
    return calls


# --------------------------------------------------------------------------- #
# Pipeline: citation-only failure is retried; success on a later draw completes.
# --------------------------------------------------------------------------- #
def test_citation_failure_is_redrafted_then_completes(tmp_path, fake_llm, monkeypatch):
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    calls = _flaky_draft(monkeypatch, fail_times=1,
                         errors=["no in-text citations [@key] present"])
    ws = tmp_path / "beta"
    r = run_topic(BETA, _cfg(), ws, provider=FixtureProvider(_WORKS),
                  llm=fake_llm, verify_doi=_verify)
    assert r.status in ("COMPLETE", "COMPLETE_NO_PDF"), r.failure
    assert calls["n"] == 2                      # one failed draw + one good draw
    assert (ws / "proposal_draft.md").exists()
    log = json.loads((ws / "run_log.json").read_text(encoding="utf-8"))
    assert log["stages"]["draft"]["status"] == "SUCCESS"


def test_transient_json_failure_is_redrafted_then_completes(tmp_path, fake_llm, monkeypatch):
    # The exact failure seen in the UI smoke test: a truncated/malformed JSON draw.
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    calls = _flaky_draft(monkeypatch, fail_times=1,
                         errors=["invalid JSON output: could not parse JSON from model "
                                 "response: '{\"text\": \"...necessitate further investig'"])
    ws = tmp_path / "beta"
    r = run_topic(BETA, _cfg(), ws, provider=FixtureProvider(_WORKS),
                  llm=fake_llm, verify_doi=_verify)
    assert r.status in ("COMPLETE", "COMPLETE_NO_PDF"), r.failure
    assert calls["n"] == 2                      # one malformed draw + one good draw
    log = json.loads((ws / "run_log.json").read_text(encoding="utf-8"))
    assert log["stages"]["draft"]["status"] == "SUCCESS"


def test_citation_failure_retries_up_to_the_cap_then_fails_closed(tmp_path, fake_llm, monkeypatch):
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    calls = _flaky_draft(monkeypatch, fail_times=99,           # never recovers
                         errors=["citation keys not in evidence_store: ['ghost2020']"])
    ws = tmp_path / "beta"
    r = run_topic(BETA, _cfg(), ws, provider=FixtureProvider(_WORKS),
                  llm=fake_llm, verify_doi=_verify)
    assert r.status == "FAILED"
    # exactly the initial attempt + the bounded retries — no more, no fewer.
    assert calls["n"] == DRAFT_REDRAFT_RETRIES + 1
    # fails closed on the SAME citation error (validation was not loosened).
    assert "citation keys not in evidence_store" in (r.failure or "")
    assert not (ws / "proposal.docx").exists()
    log = json.loads((ws / "run_log.json").read_text(encoding="utf-8"))
    assert log["stages"]["draft"]["status"] == "FAILED"


def test_non_citation_failure_fails_immediately_without_retry(tmp_path, fake_llm, monkeypatch):
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    calls = _flaky_draft(monkeypatch, fail_times=99,
                         errors=["below word floor: 10 < 75"])   # not a citation problem
    ws = tmp_path / "beta"
    r = run_topic(BETA, _cfg(), ws, provider=FixtureProvider(_WORKS),
                  llm=fake_llm, verify_doi=_verify)
    assert r.status == "FAILED"
    assert calls["n"] == 1                        # no redraft for non-citation errors
    assert "below word floor" in (r.failure or "")
