"""End-to-end pipeline test — fully offline (FakeLLM + FixtureProvider)."""
import json

import proposal_engine.render as render_mod
from proposal_engine.config import EngineConfig
from proposal_engine.pipeline import run_topic
from proposal_engine.render import RenderPDFUnavailable
from proposal_engine.topics import Topic
from proposal_engine.validators import extract_citation_keys, find_placeholders

from _helpers import FixtureProvider, make_works

TOPICS = [
    Topic(id="alpha", title="Microplastics estuarine sediment toxicity", keywords=["microplastics"]),
    Topic(id="beta", title="Federated learning privacy healthcare", keywords=["federated"]),
    Topic(id="gamma", title="Perovskite photovoltaic stability efficiency", keywords=["perovskite"]),
]
LOW = Topic(id="delta", title="Obscuretopic nichearea", keywords=["obscuretopic"])

# a DOI verifier built from all fixture works -> "verified" statuses
_ALL_WORKS = sum((make_works(t, 15) for t in ["alpha", "beta", "gamma"]), []) + make_works("delta", 3)
_DOI_MAP = {w["doi"]: {"title": w["title"], "year": str(w["year"])} for w in _ALL_WORKS}


def _verify(doi):
    return _DOI_MAP.get(doi)


def _no_pdf(*a, **k):
    raise RenderPDFUnavailable("simulated: no PDF engine on this machine")


def test_full_e2e(tmp_path, fake_llm, monkeypatch):
    # Simulate a machine with no PDF engine so the test is hermetic (no Word/LO).
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    cfg = EngineConfig(model_provider="anthropic", evidence_minimum=12, discipline="Science")
    out_root = tmp_path / "out"

    results = {}
    # ---- good topics ------------------------------------------------
    for t in TOPICS:
        prov = FixtureProvider(make_works(t.id, 15))
        r = run_topic(t, cfg, out_root / t.slug, provider=prov, llm=fake_llm,
                      verify_doi=_verify)
        results[t.id] = r

    for t in TOPICS:
        ws = out_root / t.slug
        r = results[t.id]
        assert r.status in ("COMPLETE", "COMPLETE_NO_PDF"), (t.id, r.failure)
        # docx exists
        assert (ws / "proposal.docx").exists()
        # zero placeholders in the draft
        draft = (ws / "proposal_draft.md").read_text(encoding="utf-8")
        assert find_placeholders(draft) == []
        # every in-text citation key exists in evidence_store
        evidence = json.loads((ws / "evidence_store.json").read_text(encoding="utf-8"))
        ev_keys = {e["key"] for e in evidence}
        cited = set(extract_citation_keys(draft))
        assert cited and cited <= ev_keys
        # every bibliography (references.json) entry originates from evidence_store
        refs = json.loads((ws / "references.json").read_text(encoding="utf-8"))
        assert {c["id"] for c in refs} <= ev_keys
        assert {c["id"] for c in refs} == cited  # only cited entries
        # citation audit + checklist exist
        assert (ws / "citation_audit.csv").exists()
        assert (ws / "review_checklist.md").exists()

    # ---- low-evidence topic fails safely ----------------------------
    prov = FixtureProvider(make_works("delta", 3))
    r = run_topic(LOW, cfg, out_root / LOW.slug, provider=prov, llm=fake_llm,
                  verify_doi=_verify)
    assert r.status == "FAILED"
    assert "insufficient_evidence" in (r.failure or "")
    log = json.loads((out_root / LOW.slug / "run_log.json").read_text(encoding="utf-8"))
    assert log["stages"]["evidence"]["status"] == "FAILED"


def test_failed_topic_does_not_stop_batch(tmp_path, fake_llm, monkeypatch):
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    cfg = EngineConfig(evidence_minimum=12)
    out_root = tmp_path / "out"
    batch = [LOW, TOPICS[0]]  # failing topic first, then a good one
    statuses = {}
    for t in batch:
        works = make_works(t.id, 3 if t.id == "delta" else 15)
        r = run_topic(t, cfg, out_root / t.slug, provider=FixtureProvider(works),
                      llm=fake_llm, verify_doi=_verify)
        statuses[t.id] = r.status
    assert statuses["delta"] == "FAILED"
    assert statuses["alpha"] in ("COMPLETE", "COMPLETE_NO_PDF")


def test_resumability_skips_success_stages(tmp_path, fake_llm, monkeypatch):
    monkeypatch.setattr(render_mod, "docx_to_pdf", _no_pdf)
    cfg = EngineConfig(evidence_minimum=12)
    ws = tmp_path / "out" / "alpha"
    prov = FixtureProvider(make_works("alpha", 15))
    run_topic(TOPICS[0], cfg, ws, provider=prov, llm=fake_llm, verify_doi=_verify)

    draft_mtime = (ws / "proposal_draft.md").stat().st_mtime_ns
    ev_mtime = (ws / "evidence_store.json").stat().st_mtime_ns

    # rerun without force: SUCCESS stages must be skipped (artifacts untouched)
    run_topic(TOPICS[0], cfg, ws, provider=prov, llm=fake_llm, verify_doi=_verify)
    assert (ws / "proposal_draft.md").stat().st_mtime_ns == draft_mtime
    assert (ws / "evidence_store.json").stat().st_mtime_ns == ev_mtime

    # force reruns evidence (mtime changes)
    run_topic(TOPICS[0], cfg, ws, provider=prov, llm=fake_llm, verify_doi=_verify, force=True)
    assert (ws / "evidence_store.json").stat().st_mtime_ns != ev_mtime
