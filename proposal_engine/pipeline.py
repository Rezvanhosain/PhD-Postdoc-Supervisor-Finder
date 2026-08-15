"""Per-topic pipeline orchestration with the Phase 0 resumability rule.

Dependencies (evidence provider, LLM, DOI verifier) are injected so the whole
pipeline runs offline in tests with recorded fixtures.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import bibliography as biblio
from . import candidate_context as cc
from . import draft as drafting
from . import evidence as ev
from . import intake as intake_mod
from . import review as review_mod
from . import strategy as strat_mod
from .config import EngineConfig
from .quality import document_quality_check
from .render import (RenderError, RenderPDFUnavailable, render, validate_docx,
                     validate_pdf)
from .runlog import RunLog
from .topics import Topic

ARTIFACTS = {
    "manifest": "topic_manifest.json",
    "profile": "extracted_profile.md",
    "strategy": "search_strategy.md",
    "evidence_store": "evidence_store.json",
    "evidence_table": "evidence_table.csv",
    "draft": "proposal_draft.md",
    "references": "references.json",
    "audit": "citation_audit.csv",
    "checklist": "review_checklist.md",
    "docx": "proposal.docx",
    "pdf": "proposal.pdf",
    "run_log": "run_log.json",
}

# A transient drafting failure (a citation-only miss, or a malformed/truncated
# JSON draw) is usually just LLM variance. Redraft the whole topic up to this
# many times before failing closed. Substantive validation failures never retry.
DRAFT_REDRAFT_RETRIES = 2
# Back-compat alias (retained for callers/tests that referenced the old name).
CITATION_REDRAFT_RETRIES = DRAFT_REDRAFT_RETRIES


@dataclass
class TopicResult:
    topic_id: str
    status: str = "IN_PROGRESS"
    workspace: str = ""
    failure: str | None = None
    notes: list[str] = field(default_factory=list)


def _p(workspace: Path, name_key: str) -> Path:
    return workspace / ARTIFACTS[name_key]


def _quality_serious(docx_path: Path, config: EngineConfig, result: "TopicResult") -> list[str]:
    """Run the document quality gate. Serious defects block the render (returned
    as errors); warnings are recorded as notes but do not block."""
    report = document_quality_check(
        docx_path, expected_title=config.proposal_title,
        section_names=[s.name for s in config.sections])
    for w in report["warnings"]:
        result.notes.append(f"quality warning: {w}")
    return [f"quality: {s}" for s in report["serious"]]


def run_topic(topic: Topic, config: EngineConfig, workspace: Path, *,
              provider, llm, verify_doi, profile_path: str | None = None,
              force: bool = False, evidence_only: bool = False,
              preflight: dict | None = None) -> TopicResult:
    workspace.mkdir(parents=True, exist_ok=True)
    log = RunLog(_p(workspace, "run_log"), topic.id)
    if preflight is not None:
        log.set_preflight(preflight)
    result = TopicResult(topic.id, workspace=str(workspace))

    # ---- Stage 1: Intake (manifest + optional profile) -----------------
    manifest_path = _p(workspace, "manifest")
    profile_out = _p(workspace, "profile")
    profile_text = ""
    client = topic.client or profile_path
    intake_artifacts = [manifest_path]
    if not log.can_skip("intake", intake_artifacts, force):
        manifest = {
            "topic": topic.model_dump(),
            "config": config.model_dump(),
            "client_profile_path": client or None,
        }
        if client:
            pr = intake_mod.extract_profile(client)
            intake_mod.write_profile_md(pr, profile_out)
            profile_text = pr.text
            manifest["profile_ok"] = pr.ok
            manifest["profile_reasons"] = pr.reasons
            if not pr.ok:
                manifest["profile_status"] = "NEEDS_PROFILE_REVIEW"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
        log.mark_success("intake", f"client={client or 'none'}")
    else:
        if profile_out.exists():
            profile_text = intake_mod.extract_profile(profile_out).text

    # Block drafting on poor profile
    profile_needs_review = False
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        profile_needs_review = m.get("profile_status") == "NEEDS_PROFILE_REVIEW"

    # ---- Stage 2: Search Strategy -------------------------------------
    strat_path = _p(workspace, "strategy")
    if not log.can_skip("strategy", [strat_path], force):
        try:
            strat = strat_mod.build_strategy(topic, config, llm=llm if not evidence_only else None)
        except Exception as e:
            log.mark_failed("strategy", str(e))
            result.status, result.failure = "FAILED", f"strategy: {e}"
            return result
        strat_mod.write_strategy(topic, strat, strat_path)
        log.mark_success("strategy", f"{len(strat['queries'])} queries",
                         queries=strat["queries"])
    else:
        strat = {"queries": log.data["stages"]["strategy"].get("queries", [])}
        if not strat["queries"]:  # run_log lost the queries -> rebuild deterministically
            strat = strat_mod.build_strategy(topic, config, llm=None)

    # ---- Stage 3: Evidence Build --------------------------------------
    store_path = _p(workspace, "evidence_store")
    table_path = _p(workspace, "evidence_table")
    evidence: list[dict] = []
    if not log.can_skip("evidence", [store_path, table_path], force):
        try:
            evidence = ev.build_evidence(provider, strat["queries"], config,
                                         broaden_query=topic.title)
            ev.enforce_minimum(evidence, config)
        except ev.InsufficientEvidence as e:
            ev.write_evidence_store(evidence, store_path)
            ev.write_evidence_table(evidence, table_path)
            log.mark_failed("evidence", f"insufficient_evidence ({e.found}/{e.needed})",
                            found=e.found, needed=e.needed)
            result.status = "FAILED"
            result.failure = f"insufficient_evidence ({e.found}/{e.needed})"
            return result
        except Exception as e:
            log.mark_failed("evidence", str(e))
            result.status, result.failure = "FAILED", f"evidence: {e}"
            return result
        ev.write_evidence_store(evidence, store_path)
        ev.write_evidence_table(evidence, table_path)
        log.mark_success("evidence", f"{len(evidence)} papers", count=len(evidence))
    else:
        evidence = json.loads(store_path.read_text(encoding="utf-8"))

    if evidence_only or llm is None:
        log.set_status("EVIDENCE_ONLY")
        result.status = "EVIDENCE_ONLY"
        result.notes.append(f"{len(evidence)} evidence items collected; drafting skipped "
                            "(evidence-only mode / no model key).")
        return result

    if profile_needs_review:
        log.mark_failed("draft", "blocked: NEEDS_PROFILE_REVIEW")
        result.status, result.failure = "FAILED", "NEEDS_PROFILE_REVIEW blocks drafting"
        return result

    # ---- CV de-contamination: draft from cleaned candidate facts only, and
    # collect the candidate's own proposed-direction terms to keep them out. ----
    topic_text = f"{topic.title} {topic.description}"
    cleaned_context = cc.clean_candidate_context(profile_text) if profile_text else ""
    forbidden_terms = cc.direction_terms(profile_text, topic_text) if profile_text else []
    ev_blob = cc.evidence_blob(evidence)
    if profile_text:
        cc.write_candidate_context(cleaned_context, forbidden_terms,
                                   workspace / "candidate_context.md")

    # ---- Stage 4: Draft ------------------------------------------------
    draft_path = _p(workspace, "draft")
    if not log.can_skip("draft", [draft_path], force):
        sections = None
        for attempt in range(DRAFT_REDRAFT_RETRIES + 1):
            try:
                sections = drafting.draft_proposal(llm, topic, config, cleaned_context,
                                                   evidence, forbidden_terms=forbidden_terms)
                break
            except drafting.DraftingFailed as e:
                # Redraft the whole topic on a transient failure (a citation-only
                # miss, or a malformed/truncated JSON draw); fail closed immediately
                # on any substantive validation error, and fail closed once the
                # retries are exhausted. Validation itself is unchanged — only the
                # retry policy consults is_retryable_draft_failure.
                if drafting.is_retryable_draft_failure(e) and attempt < DRAFT_REDRAFT_RETRIES:
                    log.mark("draft", "RETRY",
                             f"transient-draft redraft {attempt + 1}/"
                             f"{DRAFT_REDRAFT_RETRIES} after '{e.section_key}': {e.errors}")
                    continue
                log.mark_failed("draft", str(e))
                result.status, result.failure = "FAILED", str(e)
                return result
        drafting.write_draft(topic, config, sections, draft_path)
        log.mark_success("draft", f"{len(sections)} sections")
    draft_md = draft_path.read_text(encoding="utf-8")

    # Topic-fidelity backstop: no candidate-direction term may survive in the
    # assembled proposal unless it is in the entered topic or the evidence.
    leaked = cc.find_contamination(draft_md, forbidden_terms, topic_text, ev_blob)
    if leaked:
        log.mark_failed("draft", f"topic_fidelity: leaked {leaked}")
        result.status, result.failure = "FAILED", (
            "topic_fidelity: candidate-direction terms leaked into the proposal "
            f"and are absent from the topic/evidence: {leaked}")
        return result

    # ---- Stage 5: Bibliography + audit --------------------------------
    refs_path = _p(workspace, "references")
    audit_path = _p(workspace, "audit")
    try:
        cited_entries, csl_items = biblio.build_bibliography(draft_md, evidence)
    except biblio.CitationGateError as e:
        log.mark_failed("bibliography", str(e))
        result.status, result.failure = "FAILED", str(e)
        return result
    if not log.can_skip("bibliography", [refs_path, audit_path], force):
        biblio.write_references_json(csl_items, refs_path)
        audit_rows = biblio.audit_citations(cited_entries, verify_doi)
        biblio.write_audit_csv(audit_rows, audit_path)
        log.mark_success("bibliography", f"{len(cited_entries)} cited")
    else:
        audit_rows = biblio.audit_citations(cited_entries, verify_doi)

    # ---- Stage 6: Render ----------------------------------------------
    docx_path = _p(workspace, "docx")
    pdf_path = _p(workspace, "pdf")
    render_artifacts = [docx_path, pdf_path]
    if not log.can_skip("render", render_artifacts, force):
        section_names = [s.name for s in config.sections]
        try:
            render(draft_path, refs_path, cited_entries, docx_path, pdf_path,
                   config=config, meta=config.metadata)
        except RenderPDFUnavailable as e:
            # DOCX succeeded; PDF engine truly unavailable -> visible partial.
            docx_errors = validate_docx(docx_path, section_names)
            docx_errors += _quality_serious(docx_path, config, result)
            if docx_errors:
                log.mark_failed("render", f"docx invalid: {docx_errors}")
                result.status, result.failure = "FAILED", f"render docx: {docx_errors}"
                return result
            log.mark("render", "PARTIAL", f"PDF unavailable: {e}", pdf_error=str(e))
            result.notes.append(f"DOCX rendered; PDF skipped: {e}")
        except RenderError as e:
            log.mark_failed("render", str(e))
            result.status, result.failure = "FAILED", f"render: {e}"
            return result
        else:
            errors = validate_docx(docx_path, section_names)
            errors += validate_pdf(pdf_path)
            errors += _quality_serious(docx_path, config, result)
            if errors:
                log.mark_failed("render", f"validation: {errors}")
                result.status, result.failure = "FAILED", f"render validation: {errors}"
                return result
            log.mark_success("render", "docx+pdf validated")

    # ---- Stage 7: Review checklist ------------------------------------
    checklist_path = _p(workspace, "checklist")
    if not log.can_skip("review", [checklist_path], force):
        text = review_mod.build_checklist(topic, evidence, audit_rows, draft_md,
                                          config.evidence_minimum)
        review_mod.write_checklist(text, checklist_path)
        log.mark_success("review", "checklist written")

    if log.stage_status("render") == "PARTIAL":
        log.set_status("COMPLETE_NO_PDF")
        result.status = "COMPLETE_NO_PDF"
    else:
        log.set_status("COMPLETE")
        result.status = "COMPLETE"
    return result
