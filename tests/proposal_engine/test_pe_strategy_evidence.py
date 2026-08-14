from proposal_engine.config import EngineConfig
from proposal_engine.evidence import (InsufficientEvidence, build_evidence,
                                       dedupe, deterministic_relevance,
                                       enforce_minimum)
from proposal_engine.strategy import build_strategy, deterministic_strategy
from proposal_engine.topics import Topic

from _helpers import FixtureProvider, make_works


def test_deterministic_strategy_min_queries():
    t = Topic(id="t1", title="Microplastics in estuarine sediment toxicity")
    strat = deterministic_strategy(t, EngineConfig(discipline="Environmental Science"))
    assert strat["mode"] == "deterministic"
    assert len(strat["queries"]) >= 3
    assert strat["inclusion_criteria"]


def test_build_strategy_without_llm_is_deterministic():
    t = Topic(id="t1", title="Federated learning privacy healthcare")
    strat = build_strategy(t, EngineConfig(), llm=None)
    assert strat["mode"] == "deterministic"


def test_dedupe_by_doi():
    a = {"title": "X", "doi": "10.1/A", "abstract": "", "authors": ["Q"], "source_ids": {}}
    b = {"title": "X copy", "doi": "10.1/a", "abstract": "now has one", "authors": ["Q"],
         "source_ids": {}}
    out = dedupe([a, b])
    assert len(out) == 1
    assert out[0]["abstract"] == "now has one"  # merged from duplicate


def test_dedupe_by_fuzzy_title_without_doi():
    a = {"title": "Deep learning for medical imaging", "doi": "", "abstract": "a",
         "authors": ["Q"], "source_ids": {}}
    b = {"title": "Deep learning for medical imaging.", "doi": "", "abstract": "b",
         "authors": ["Q"], "source_ids": {}}
    assert len(dedupe([a, b])) == 1


def test_deterministic_relevance_mentions_terms():
    e = {"title": "microplastics in water", "abstract": "toxicity of sediment",
         "cited_by": 3}
    note = deterministic_relevance(e, {"microplastics", "toxicity", "sediment"})
    assert "microplastics" in note
    assert note.startswith("Relevant because")


def test_build_evidence_assigns_keys_and_notes():
    prov = FixtureProvider(make_works("alpha", 15))
    cfg = EngineConfig(evidence_minimum=12)
    t = Topic(id="a", title="Microplastics estuarine sediment toxicity")
    evidence = build_evidence(prov, build_strategy(t, cfg, llm=None)["queries"], cfg,
                              broaden_query=t.title)
    assert len(evidence) == 15
    keys = [e["key"] for e in evidence]
    assert len(set(keys)) == len(keys)  # unique keys
    assert all(e["relevance_note"] for e in evidence)
    enforce_minimum(evidence, cfg)  # should not raise


def test_low_evidence_raises():
    prov = FixtureProvider(make_works("delta", 3))
    cfg = EngineConfig(evidence_minimum=12)
    t = Topic(id="d", title="Obscuretopic nichearea")
    evidence = build_evidence(prov, [t.title], cfg, broaden_query=t.title)
    try:
        enforce_minimum(evidence, cfg)
        assert False, "should have raised"
    except InsufficientEvidence as e:
        assert e.found == 3 and e.needed == 12
