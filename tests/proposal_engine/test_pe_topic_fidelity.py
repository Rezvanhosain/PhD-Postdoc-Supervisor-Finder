"""Regression tests for the topic-fidelity / stale-output bug.

Symptom that motivated these: the UI produced a proposal about the candidate's
CV-stated 'proposed PhD direction' (Industrial IoT predictive maintenance) and
stamped a demo applicant name ('Jordan Rivera'), instead of writing about the
topic the user typed. These tests pin the fixes. All offline — no live API.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from proposal_engine.config import EngineConfig, load_config
from proposal_engine.draft import draft_section, render_draft_md
from proposal_engine.pipeline import ARTIFACTS, TopicResult
from proposal_engine.topics import Topic

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO / "proposal_engine" / "examples" / "config.yaml"

# The candidate's CV states this as a "proposed PhD direction". It must never be
# what the proposal is written about unless the user's TOPIC actually asks for it.
CV_DIRECTION = (
    "PROFESSIONAL SUMMARY. Proposed PhD direction: Availability-aware clustered "
    "federated continual learning for predictive maintenance in Industrial IoT "
    "edge systems. Research interests: AI, machine learning, data science."
)


# --------------------------------------------------------------------------- #
# 1. The default/example config carries no demo candidate or demo title.
# --------------------------------------------------------------------------- #
def test_default_config_has_no_demo_applicant_or_title():
    cfg = load_config(DEFAULT_CONFIG)
    assert cfg.applicant_name is None, "default config must not hard-code an applicant name"
    assert cfg.proposal_title is None, "default config must not hard-code a proposal title"
    # metadata() only includes set fields -> no applicant/title leaks to the page.
    assert "applicant_name" not in cfg.metadata
    assert "proposal_title" not in cfg.metadata


def test_default_config_text_has_no_sample_person_or_demo_title():
    raw = DEFAULT_CONFIG.read_text(encoding="utf-8").lower()
    assert "jordan rivera" not in raw
    assert "availability-aware" not in raw
    assert "predictive maintenance" not in raw


# --------------------------------------------------------------------------- #
# 2. The drafting prompt makes the TOPIC authoritative and tells the model to
#    ignore any 'proposed direction' stated in the CV.
# --------------------------------------------------------------------------- #
class _RecordingLLM:
    """Captures the exact system/user prompt, returns one valid title."""

    def __init__(self) -> None:
        self.system = ""
        self.user = ""

    def generate_json(self, system: str, user: str, max_tokens: int = 0):
        self.system, self.user = system, user
        return {"text": "A Focused Bayesian Federated Learning Study for Bioinformatics Applications"}


def _title_section():
    return {"key": "title", "name": "Title", "words": 12}


def test_draft_prompt_makes_topic_authoritative_and_ignores_cv_direction():
    topic = Topic(id="001", title="Artificial Intelligence, Machine Learning, Data "
                                  "Science, Bayesian Data Analysis, Federated Learning, "
                                  "and Bioinformatics.")
    llm = _RecordingLLM()
    out = draft_section(llm, topic, EngineConfig(), CV_DIRECTION,
                        evidence=[{"key": "k1", "title": "t", "year": 2020, "abstract": "a"}],
                        section=_title_section(), prior_summaries={})
    assert out  # produced a title

    sys_low = llm.system.lower()
    # System prompt anchors on the topic and neutralises the CV's stated direction.
    assert "authoritative research subject" in sys_low
    assert "ignore" in sys_low and "direction" in sys_low

    user_low = llm.user.lower()
    assert "authoritative research subject" in user_low
    assert "fit only" in user_low or "background for fit" in user_low
    # The topic text is in the prompt; the CV text is clearly demoted, not the subject.
    assert "bayesian data analysis" in user_low


def test_title_section_hint_is_present_and_forbids_field_lists():
    topic = Topic(id="001", title="AI, ML, Data Science, Federated Learning, Bioinformatics")
    llm = _RecordingLLM()
    draft_section(llm, topic, EngineConfig(), "", evidence=[], section=_title_section(),
                  prior_summaries={})
    user_low = llm.user.lower()
    assert "concise, specific proposal title" in user_low
    assert "not a comma-separated list of fields" in user_low


# --------------------------------------------------------------------------- #
# 3. Two different topics yield two different titles; a global config title does
#    not override the per-topic drafted title by default.
# --------------------------------------------------------------------------- #
def test_two_topics_produce_different_titles():
    cfg = EngineConfig()  # no proposal_title set
    t1 = Topic(id="001", title="AI, ML, Bayesian Data Analysis, Federated Learning, Bioinformatics")
    t2 = Topic(id="002", title="Deep Learning, Sequential Modeling, NLP, Computer Vision")
    md1 = render_draft_md(t1, cfg, {"title": "Federated Bayesian Models for Genomic Inference"})
    md2 = render_draft_md(t2, cfg, {"title": "Sequence-to-Vision Representation Learning for Video"})
    h1 = md1.splitlines()[0]
    h2 = md2.splitlines()[0]
    assert h1.startswith("# ") and h2.startswith("# ")
    assert h1 != h2
    # Neither title was hijacked by the CV's Industrial-IoT direction.
    assert "industrial iot" not in (h1 + h2).lower()


def test_config_proposal_title_is_opt_in_only():
    # Default: no proposal_title -> per-topic drafted title wins (builder uses
    # `meta.get("proposal_title") or drafted_title`).
    assert "proposal_title" not in EngineConfig().metadata
    # When explicitly supplied for a specific run, it is carried (opt-in override).
    assert EngineConfig(proposal_title="My Exact Title").metadata["proposal_title"] == "My Exact Title"


# --------------------------------------------------------------------------- #
# 4. --force / Regenerate removes last run's rendered files, so a failed rerun
#    can never surface a stale DOCX/PDF for download; a successful rerun serves
#    the freshly written file.
# --------------------------------------------------------------------------- #
def _patch_offline(monkeypatch, tmp_path):
    from desktop_app import jobs
    monkeypatch.setattr(jobs, "run_preflight", lambda cfg: {"can_run": True, "model_key": True})
    monkeypatch.setattr(jobs, "preflight_messages", lambda pre: [])
    monkeypatch.setattr(jobs.factory, "build_http_client", lambda p: object())
    monkeypatch.setattr(jobs.factory, "build_provider", lambda http: object())
    monkeypatch.setattr(jobs.factory, "build_llm", lambda cfg: object())
    monkeypatch.setattr(jobs.factory, "build_verify_doi", lambda http: object())
    return jobs


def _make_job(jobs, out: Path):
    job = jobs.Job(id="testjob", out_dir=str(out.resolve()))
    job.topics = [jobs.TopicStatus(id="001", title="AI, ML, Bioinformatics")]
    return job


def test_force_regenerate_removes_stale_output_on_failed_run(monkeypatch, tmp_path):
    jobs = _patch_offline(monkeypatch, tmp_path)
    out = tmp_path / "out"
    ws = out / "001"
    ws.mkdir(parents=True)
    stale = ws / ARTIFACTS["docx"]
    stale.write_bytes(b"STALE-FROM-PREVIOUS-RUN")

    # This run fails before rendering and writes nothing new.
    def failing_run_topic(topic, cfg, ws_, **kw):
        return TopicResult(topic.id, status="FAILED", failure="boom")

    monkeypatch.setattr(jobs, "run_topic", failing_run_topic)

    job = _make_job(jobs, out)
    jobs._run_job(job, [{"id": "001", "title": "AI, ML, Bioinformatics"}],
                  None, out, None, True)

    assert not stale.exists(), "force must clear last run's stale DOCX before regenerating"
    assert job.topics[0].status == "failed"
    assert job.topics[0].docx is None, "a failed run must not surface any DOCX to download"


def test_force_regenerate_serves_freshly_written_output(monkeypatch, tmp_path):
    jobs = _patch_offline(monkeypatch, tmp_path)
    out = tmp_path / "out"
    ws = out / "001"
    ws.mkdir(parents=True)
    (ws / ARTIFACTS["docx"]).write_bytes(b"STALE")
    (ws / "stale_only.txt").write_bytes(b"LEFTOVER")  # non-rendered stale artifact

    def ok_run_topic(topic, cfg, ws_, **kw):
        # Faithful to the real pipeline, which mkdir's its workspace up front.
        ws_.mkdir(parents=True, exist_ok=True)
        (ws_ / ARTIFACTS["docx"]).write_bytes(b"FRESH")
        return TopicResult(topic.id, status="COMPLETE", failure=None)

    monkeypatch.setattr(jobs, "run_topic", ok_run_topic)

    job = _make_job(jobs, out)
    jobs._run_job(job, [{"id": "001", "title": "AI, ML, Bioinformatics"}],
                  None, out, None, True)

    ts = job.topics[0]
    assert ts.status == "done"
    assert ts.docx is not None
    assert Path(ts.docx).read_bytes() == b"FRESH", "the served DOCX must be this run's output"
    # force quarantines the WHOLE prior workspace, so no stale sibling survives
    # into the fresh run's folder.
    assert not (ws / "stale_only.txt").exists(), \
        "force must quarantine the entire prior workspace, not just DOCX/PDF"
