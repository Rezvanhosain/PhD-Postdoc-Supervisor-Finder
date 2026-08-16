"""Background job runner for the local desktop UI.

This is a thin usability wrapper around the EXISTING proposal_engine pipeline —
it does not change any generation logic. It writes the topics/config the user
typed into temp files (so the normal loaders run), then calls ``run_topic`` for
each topic on a worker thread and records status/artifacts/warnings for the UI
to poll.
"""
from __future__ import annotations

import csv
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from proposal_engine import factory
from proposal_engine import intake as intake_mod
from proposal_engine import profile_gate as pg
from proposal_engine.config import EngineConfig, load_config
from proposal_engine.pipeline import ARTIFACTS, run_topic
from proposal_engine.preflight import preflight_messages, run_preflight
from proposal_engine.topics import Topic, load_topics, slugify

# Default config shipped with the engine (used when the user picks "default").
DEFAULT_CONFIG = Path("proposal_engine/examples/config.yaml")
DEFAULT_OUT = Path("proposal_engine_out")


@dataclass
class TopicStatus:
    id: str
    title: str
    status: str = "queued"          # queued | running | done | failed
    docx: str | None = None
    pdf: str | None = None
    evidence: int | None = None
    cited: int | None = None
    audit: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    # Profile-review gate surfaced to the UI (never a file-only workflow).
    personalization: str | None = None       # full | safe_facts | none
    profile_severity: str | None = None       # ok | warning | critical
    profile_blocking: str | None = None       # "" | data | file
    profile_flags: list = field(default_factory=list)  # [{code,severity,message,field,consequence}]
    profile_default_mode: str | None = None
    profile_allow_override: bool = True


@dataclass
class Job:
    id: str
    status: str = "queued"          # queued | running | done | error
    message: str = ""
    out_dir: str = ""
    preflight: list[str] = field(default_factory=list)
    topics: list[TopicStatus] = field(default_factory=list)


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def get_job(job_id: str) -> Job | None:
    with _LOCK:
        return _JOBS.get(job_id)


def job_dict(job: Job) -> dict:
    return asdict(job)


def parse_topic_lines(raw: str) -> list[dict]:
    """Turn the textarea (one topic per line, optional 'id | title') into topic
    dicts. Never raises on ordinary input — blank lines are skipped."""
    topics: list[dict] = []
    seen: set[str] = set()
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            tid, title = (p.strip() for p in line.split("|", 1))
        else:
            title, tid = line, ""
        if not title:
            continue
        tid = slugify(tid or title)
        while tid in seen:            # keep ids unique
            tid = tid + "-x"
        seen.add(tid)
        topics.append({"id": tid, "title": title})
    return topics


def write_topics_file(topic_dicts: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"topics": topic_dicts}, sort_keys=False,
                                    allow_unicode=True), encoding="utf-8")
    return path


def resolve_config_file(config_path: str | None, out_dir: Path) -> Path:
    """Return a usable config.yaml path: the user's file if given, else a copy of
    the shipped default written into the output folder (so a record is kept)."""
    if config_path and Path(config_path).is_file():
        return Path(config_path)
    src = DEFAULT_CONFIG if DEFAULT_CONFIG.is_file() else None
    dest = out_dir / "_ui_config.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src is not None:
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    else:  # last resort: a minimal valid default
        dest.write_text(yaml.safe_dump(EngineConfig().model_dump(mode="json"),
                                       sort_keys=False), encoding="utf-8")
    return dest


def _quarantine_workspace(out: Path, ws: Path) -> Path | None:
    """Move an existing per-topic workspace aside before a force regenerate so no
    stale artifact (DOCX/PDF/draft/evidence/run_log) can survive into — or be
    downloaded from — the fresh run. Returns the quarantine path, or None if there
    was nothing to move. Move (not delete): this folder is not under version
    control, so nothing is destroyed."""
    if not ws.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = out / "_quarantine" / stamp / ws.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ws), str(dest))
    return dest


def _audit_summary(audit_csv: Path) -> dict:
    if not audit_csv.is_file():
        return {}
    counts: dict[str, int] = {}
    try:
        for row in csv.DictReader(audit_csv.open(encoding="utf-8")):
            counts[row["status"]] = counts.get(row["status"], 0) + 1
    except Exception:  # pragma: no cover - malformed CSV should not crash the UI
        return {}
    return counts


def precheck_profile(cv_path: str | None, applicant_name: str | None = None) -> dict:
    """Extract the CV and evaluate the profile-review gate WITHOUT generating, so
    the UI can show exactly what was flagged (field/sentence/file), whether it is a
    warning or a critical blocker, what proceeding will do, and which choices are
    allowed — before the user commits to generation."""
    if not cv_path:
        gate = pg.evaluate_profile_gate(reasons=[], profile_text="",
                                        applicant_name=applicant_name, profile_provided=False)
        return {"provided": False, "extracted_name": "", **gate.to_dict()}
    pr = intake_mod.extract_profile(cv_path)
    gate = pg.evaluate_profile_gate(
        reasons=pr.reasons, profile_text=pr.text, applicant_name=applicant_name,
        profile_provided=True, source_name=Path(pr.source or cv_path).name)
    return {"provided": True, "extracted_name": pg.extracted_applicant_name(pr.text),
            **gate.to_dict()}


def start_job(*, topics_raw: str, config_path: str | None, out_dir: str | None,
              cv_path: str | None, force: bool = True, profile_mode: str = "auto",
              applicant_name: str | None = None) -> str:
    """Validate input, create a Job, and launch the worker thread. Returns job id."""
    out = Path(out_dir) if out_dir else DEFAULT_OUT
    topic_dicts = parse_topic_lines(topics_raw)
    job = Job(id=uuid.uuid4().hex[:12], out_dir=str(out.resolve()))
    if not topic_dicts:
        job.status = "error"
        job.message = "Please enter at least one research topic."
        with _LOCK:
            _JOBS[job.id] = job
        return job.id
    job.topics = [TopicStatus(id=t["id"], title=t["title"]) for t in topic_dicts]
    with _LOCK:
        _JOBS[job.id] = job
    thread = threading.Thread(target=_run_job, name=f"pe-job-{job.id}",
                              args=(job, topic_dicts, config_path, out, cv_path, force,
                                    profile_mode, applicant_name),
                              daemon=True)
    thread.start()
    return job.id


def _run_job(job: Job, topic_dicts: list[dict], config_path: str | None,
             out: Path, cv_path: str | None, force: bool,
             profile_mode: str = "auto", applicant_name: str | None = None) -> None:
    try:
        out.mkdir(parents=True, exist_ok=True)
        cfg_file = resolve_config_file(config_path, out)
        topics_file = write_topics_file(topic_dicts, out / "_ui_topics.yaml")
        cfg = load_config(cfg_file)
        topic_list = load_topics(topics_file)

        pre = run_preflight(cfg)
        job.preflight = preflight_messages(pre)
        if not pre["can_run"]:
            job.status = "error"
            job.message = ("Blocked: OPENALEX_API_KEY is required before any scholarly "
                           "API call. Set it in .env and restart.")
            return

        eff_evidence_only = not pre["model_key"]
        if eff_evidence_only:
            job.preflight.append("No model key found — running EVIDENCE-ONLY (no draft/DOCX).")

        http = factory.build_http_client(out / ".http_cache")
        provider = factory.build_provider(http)
        llm = None if eff_evidence_only else factory.build_llm(cfg)
        verify_doi = factory.build_verify_doi(http)

        job.status = "running"
        by_id = {t.id: t for t in job.topics}
        for i, t in enumerate(topic_list.topics, start=1):
            ts = by_id.get(t.id)
            if ts is None:
                continue
            ts.status = "running"
            job.message = f"Generating {i}/{len(topic_list.topics)}: {t.title}"
            ws = out / t.slug
            # On a from-scratch regenerate, quarantine the ENTIRE prior workspace
            # up front so no stale artifact (DOCX/PDF/draft/evidence/run_log) can
            # survive into — or be downloaded from — the fresh run. force=True makes
            # every stage regenerate, so nothing in the old workspace is reused.
            if force:
                try:
                    _quarantine_workspace(out, ws)
                except OSError:
                    pass
            try:
                r = run_topic(t, cfg, ws, provider=provider, llm=llm,
                              verify_doi=verify_doi, profile_path=cv_path or None,
                              force=force, evidence_only=eff_evidence_only, preflight=pre,
                              profile_mode=profile_mode, applicant_name=applicant_name)
            except Exception as e:  # never let one topic abort the batch
                ts.status = "failed"
                ts.error = str(e)
                continue
            ts.warnings = [n for n in r.notes if "warning" in n.lower() or "skipped" in n.lower()]
            # Surface the profile-review gate + personalization mode on every topic
            # so the UI can explain what was flagged and how the CV was (or wasn't) used.
            ts.personalization = r.personalization or None
            g = r.profile_gate or {}
            ts.profile_severity = g.get("severity")
            ts.profile_blocking = g.get("blocking_class")
            ts.profile_flags = g.get("flags", [])
            ts.profile_default_mode = g.get("default_mode")
            ts.profile_allow_override = bool(g.get("allow_override_without_personalization", True))
            if r.failure:
                ts.status = "failed"
                ts.error = r.failure
            else:
                ts.status = "done"
            # Only expose the freshly rendered files, and only for a topic that
            # actually completed — never surface a stale artifact for a failed run.
            docx = ws / ARTIFACTS["docx"]
            pdf = ws / ARTIFACTS["pdf"]
            ts.docx = str(docx) if (ts.status == "done" and docx.is_file()) else None
            ts.pdf = str(pdf) if (ts.status == "done" and pdf.is_file()) else None
            ts.audit = _audit_summary(ws / ARTIFACTS["audit"])
            store = ws / ARTIFACTS["evidence_store"]
            if store.is_file():
                import json
                try:
                    ts.evidence = len(json.loads(store.read_text(encoding="utf-8")))
                except Exception:
                    ts.evidence = None
            refs = ws / ARTIFACTS["references"]
            if refs.is_file():
                import json
                try:
                    ts.cited = len(json.loads(refs.read_text(encoding="utf-8")))
                except Exception:
                    ts.cited = None

        done = sum(1 for t in job.topics if t.status == "done")
        job.status = "done"
        job.message = f"Finished: {done}/{len(job.topics)} proposal(s) generated."
    except Exception as e:  # top-level guard so the UI always sees a terminal state
        job.status = "error"
        job.message = f"Unexpected error: {e}"
