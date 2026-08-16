"""Profile-review gate: decision logic, personalization modes, and the pipeline
behaviour that replaces the old opaque "NEEDS_PROFILE_REVIEW blocks drafting".

All offline (FakeLLM + FixtureProvider). Nothing here weakens topic-fidelity,
citation, evidence, quarantine, or quality checks — it only governs which profile
text (if any) reaches drafting, and makes the reason visible/structured.
"""
from __future__ import annotations

import json

import pytest

import proposal_engine.profile_gate as pg
import proposal_engine.render as render_mod
from proposal_engine.config import EngineConfig
from proposal_engine.pipeline import run_topic
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


def _run(tmp_path, monkeypatch, cv, *, profile_mode="auto", applicant_name=None):
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    ws = tmp_path / "beta"
    return run_topic(BETA, _cfg(), ws, provider=FixtureProvider(_WORKS),
                     llm=__import__("_helpers").FakeLLM(), verify_doi=_verify,
                     profile_path=str(cv), profile_mode=profile_mode,
                     applicant_name=applicant_name, force=True), ws


# --- CV fixtures on disk --------------------------------------------------- #
def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


WARN_SAFE = ("ARSALAN JAVED\nMaster of Science in Computer Science, CECOS "
             "University. Worked as Assistant Director at NADRA. Skills: Python, SQL.")
UNCERTAIN = "ARSALAN JAVED\nSome vague lines about nothing much here at all today."
CLEAN_WITH_ODD = (
    "ARSALAN JAVED\nMaster of Science in Computer Science, CECOS University, "
    "Peshawar. Worked as Assistant Director at NADRA for over a decade. Skills "
    "include Python, SQL, and networking administration across public systems. "
    "My secret ambition is to breed rare orchids in Antarctica someday.")
WRONG_PERSON = (
    "JOHN SMITH\nMaster of Science in Computer Science, Example University. "
    "Worked as a Software Engineer for several years. Skills include Java and "
    "C++ development, plus database administration on large public systems.")


# =========================================================================== #
# Unit: gate classification, defaults, resolution, safe-facts filtering.
# =========================================================================== #
def test_warning_defaults_to_safe_facts_when_safe_content_exists():
    g = pg.evaluate_profile_gate(reasons=["extracted profile too short (120 < 200 chars)"],
                                 profile_text=WARN_SAFE, applicant_name=None,
                                 profile_provided=True)
    assert g.severity == "warning" and g.default_mode == pg.SAFE_FACTS
    assert g.flags and g.flags[0].severity == "warning"
    assert pg.resolve_personalization(g, "auto") == (pg.SAFE_FACTS, "")


def test_warning_defaults_to_none_when_too_uncertain():
    g = pg.evaluate_profile_gate(reasons=["extracted profile too short (60 < 200 chars)"],
                                 profile_text=UNCERTAIN, applicant_name=None,
                                 profile_provided=True)
    assert g.severity == "warning" and g.default_mode == pg.NONE


def test_safe_profile_facts_keeps_safe_and_drops_uncertain_and_direction():
    src = ("ARSALAN JAVED\nProposed PhD direction: predictive maintenance in IIoT.\n"
           "Master of Science in Computer Science, CECOS University. My secret "
           "ambition is to breed rare orchids in Antarctica.")
    safe = pg.safe_profile_facts(src)
    assert "cecos university" in safe.lower()
    assert "predictive maintenance" not in safe.lower()  # proposed direction removed
    assert "orchids" not in safe.lower()                 # unmarked/uncertain removed


def test_file_critical_blocks_and_cannot_be_overridden():
    g = pg.evaluate_profile_gate(reasons=["extraction failed: bad zip"], profile_text="",
                                 applicant_name=None, profile_provided=True)
    assert g.severity == "critical" and g.blocking_class == "file"
    assert g.allow_override_without_personalization is False
    # even asking for "none" cannot rescue a corrupt file
    assert pg.resolve_personalization(g, "none")[0] == pg.BLOCK
    assert pg.resolve_personalization(g, "auto")[0] == pg.BLOCK


def test_identity_conflict_blocks_by_default_but_none_proceeds():
    g = pg.evaluate_profile_gate(reasons=[], profile_text=WRONG_PERSON,
                                 applicant_name="Arsalan Javed", profile_provided=True)
    assert g.severity == "critical" and g.blocking_class == "data"
    assert g.allow_override_without_personalization is True
    assert pg.resolve_personalization(g, "auto")[0] == pg.BLOCK
    assert pg.resolve_personalization(g, "none") == (pg.NONE, "")


def test_full_is_never_forced_over_a_warning():
    g = pg.evaluate_profile_gate(reasons=["extracted profile too short (120 < 200 chars)"],
                                 profile_text=WARN_SAFE, applicant_name=None,
                                 profile_provided=True)
    # requesting "full" on a flagged profile is downgraded to the safe default
    assert pg.resolve_personalization(g, "full")[0] == pg.SAFE_FACTS


# =========================================================================== #
# Pipeline: the required end-to-end behaviours.
# =========================================================================== #
def test_warning_is_not_blocked_and_is_surfaced_structurally(tmp_path, monkeypatch):
    cv = _write(tmp_path, "cv.txt", WARN_SAFE)
    r, ws = _run(tmp_path, monkeypatch, cv, profile_mode="auto")
    assert r.status in ("COMPLETE", "COMPLETE_NO_PDF"), r.failure   # NOT blocked
    assert r.personalization == pg.SAFE_FACTS
    # the reason is structured on the result (the UI reads this, not a file)
    assert r.profile_gate["severity"] == "warning"
    assert any(f["code"] == "too_short" for f in r.profile_gate["flags"])
    assert r.profile_gate["flags"][0]["consequence"]                # human-readable


def test_user_can_proceed_with_safe_facts(tmp_path, monkeypatch):
    cv = _write(tmp_path, "cv.txt", CLEAN_WITH_ODD)
    r, ws = _run(tmp_path, monkeypatch, cv, profile_mode="safe_facts")
    assert r.status in ("COMPLETE", "COMPLETE_NO_PDF"), r.failure
    assert r.personalization == pg.SAFE_FACTS
    # the uncertain/unmarked claim never reaches the drafting context...
    ctx = (ws / "candidate_context.md").read_text(encoding="utf-8").lower()
    assert "orchids" not in ctx
    assert "cecos university" in ctx                                # safe facts kept
    # ...nor the generated proposal
    draft = (ws / "proposal_draft.md").read_text(encoding="utf-8").lower()
    assert "orchids" not in draft


def test_user_can_proceed_without_personalization(tmp_path, monkeypatch):
    cv = _write(tmp_path, "cv.txt", CLEAN_WITH_ODD)
    r, ws = _run(tmp_path, monkeypatch, cv, profile_mode="none")
    assert r.status in ("COMPLETE", "COMPLETE_NO_PDF"), r.failure
    assert r.personalization == pg.NONE
    ctx = (ws / "candidate_context.md").read_text(encoding="utf-8").lower()
    assert "cecos university" not in ctx and "orchids" not in ctx   # no candidate facts


def test_identity_conflict_blocked_by_default_with_exact_reason(tmp_path, monkeypatch):
    cv = _write(tmp_path, "cv.txt", WRONG_PERSON)
    r, ws = _run(tmp_path, monkeypatch, cv, profile_mode="auto",
                 applicant_name="Arsalan Javed")
    assert r.status == "FAILED"
    assert "Profile blocked" in (r.failure or "")
    assert "identity" in (r.failure or "").lower() or "does not match" in (r.failure or "")
    assert "JOHN SMITH" in (r.failure or "")            # the exact conflicting field
    assert "blocks drafting" not in (r.failure or "")   # never the old vague message


def test_identity_conflict_proceeds_when_generating_without_personalization(tmp_path, monkeypatch):
    cv = _write(tmp_path, "cv.txt", WRONG_PERSON)
    r, ws = _run(tmp_path, monkeypatch, cv, profile_mode="none",
                 applicant_name="Arsalan Javed")
    assert r.status in ("COMPLETE", "COMPLETE_NO_PDF"), r.failure
    assert r.personalization == pg.NONE
    ctx = (ws / "candidate_context.md").read_text(encoding="utf-8").lower()
    assert "john smith" not in ctx                       # wrong identity never inserted


def test_corrupt_cv_stays_blocked_even_without_personalization(tmp_path, monkeypatch):
    cv = _write(tmp_path, "cv.txt", "�" * 300)      # garbled -> corrupt
    r, ws = _run(tmp_path, monkeypatch, cv, profile_mode="none")   # override attempt
    assert r.status == "FAILED"
    assert "Profile blocked" in (r.failure or "")
    assert "blocks drafting" not in (r.failure or "")
    assert not (ws / "proposal.docx").exists()


def test_run_log_records_personalization_mode_and_warning_details(tmp_path, monkeypatch):
    cv = _write(tmp_path, "cv.txt", WARN_SAFE)
    r, ws = _run(tmp_path, monkeypatch, cv, profile_mode="auto")
    log = json.loads((ws / "run_log.json").read_text(encoding="utf-8"))
    assert log["personalization"]["mode"] == pg.SAFE_FACTS
    flags = log["personalization"]["gate"]["flags"]
    assert any(f["code"] == "too_short" for f in flags)
    assert flags[0]["field"] and flags[0]["consequence"]
