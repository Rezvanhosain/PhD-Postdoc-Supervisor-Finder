"""Phase 0 CLI for the proposal engine.

    python -m proposal_engine run topics.yaml --config config.yaml \
        [--client <dir>] [--force] [--topic <id>] [--evidence-only] [--out <dir>]
    python -m proposal_engine approve <topic-id> [--out <dir>]
"""
from __future__ import annotations

from pathlib import Path

import typer

from . import factory
from .config import load_config
from .pipeline import ARTIFACTS, run_topic
from .preflight import preflight_messages, run_preflight
from .runlog import RunLog
from .topics import load_topics, slugify

app = typer.Typer(add_completion=False, help="Phase 0 topic-to-proposal engine.")

DEFAULT_OUT = "proposal_engine_out"


@app.command()
def run(
    topics_file: str = typer.Argument(..., help="Path to topics.yaml"),
    config: str = typer.Option("config.yaml", "--config", help="Path to config.yaml"),
    client: str | None = typer.Option(None, "--client", help="Default client CV/profile file or dir"),
    force: bool = typer.Option(False, "--force", help="Rerun every stage for selected topics"),
    topic: str | None = typer.Option(None, "--topic", help="Run only this topic id"),
    evidence_only: bool = typer.Option(False, "--evidence-only", help="Stop after evidence build"),
    out: str = typer.Option(DEFAULT_OUT, "--out", help="Output root directory"),
) -> None:
    cfg = load_config(config)
    topic_list = load_topics(topics_file)
    out_root = Path(out)
    out_root.mkdir(parents=True, exist_ok=True)

    pre = run_preflight(cfg)
    typer.echo("== Preflight ==")
    for line in preflight_messages(pre):
        typer.echo(line)
    typer.echo(f"openalex_key={pre['openalex_key']} model_key={pre['model_key']} "
               f"pandoc={pre['pandoc']} pdf_engine={pre['pdf_engine']}")

    if not pre["can_run"]:
        typer.echo("\nBLOCKED: OPENALEX_API_KEY is required before any scholarly API call.",
                   err=True)
        raise typer.Exit(code=2)

    eff_evidence_only = evidence_only or not pre["model_key"]

    cache_dir = out_root / ".http_cache"
    http = factory.build_http_client(cache_dir)
    provider = factory.build_provider(http)
    llm = None if eff_evidence_only else factory.build_llm(cfg)
    verify_doi = factory.build_verify_doi(http)

    topics = topic_list.topics
    if topic:
        topics = [t for t in topics if t.id == topic]
        if not topics:
            typer.echo(f"No topic with id {topic!r}", err=True)
            raise typer.Exit(code=1)

    results = []
    for t in topics:
        ws = out_root / t.slug
        typer.echo(f"\n== Topic {t.id}: {t.title} ==")
        try:
            r = run_topic(t, cfg, ws, provider=provider, llm=llm, verify_doi=verify_doi,
                          profile_path=client, force=force,
                          evidence_only=eff_evidence_only, preflight=pre)
        except Exception as e:  # never let one topic abort the batch
            typer.echo(f"  ERROR (continuing batch): {e}", err=True)
            results.append((t.id, f"ERROR: {e}", str(ws)))
            continue
        for n in r.notes:
            typer.echo(f"  - {n}")
        typer.echo(f"  status: {r.status}"
                   + (f"  ({r.failure})" if r.failure else ""))
        results.append((t.id, r.status, str(ws)))

    typer.echo("\n== Summary ==")
    for tid, status, ws in results:
        typer.echo(f"  {tid}: {status}  -> {ws}")


@app.command()
def approve(
    topic_id: str = typer.Argument(..., help="Topic id to mark FINAL"),
    out: str = typer.Option(DEFAULT_OUT, "--out", help="Output root directory"),
) -> None:
    ws = Path(out) / slugify(topic_id)
    run_log_path = ws / ARTIFACTS["run_log"]
    if not run_log_path.exists():
        typer.echo(f"No run_log found for topic {topic_id!r} at {run_log_path}", err=True)
        raise typer.Exit(code=1)
    log = RunLog(run_log_path, topic_id)
    checklist = ws / ARTIFACTS["checklist"]
    if not checklist.exists():
        typer.echo(f"Cannot approve: review checklist missing ({checklist}). "
                   "The topic must complete drafting/render first.", err=True)
        raise typer.Exit(code=1)
    docx = ws / ARTIFACTS["docx"]
    if not docx.exists():
        typer.echo(f"Cannot approve: proposal.docx missing ({docx}).", err=True)
        raise typer.Exit(code=1)
    log.approve()
    typer.echo(f"Topic {topic_id!r} marked FINAL in {run_log_path}")


if __name__ == "__main__":  # pragma: no cover
    app()
