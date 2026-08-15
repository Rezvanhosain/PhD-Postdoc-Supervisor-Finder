# proposal_engine — Phase 0

An isolated internal package that turns **research topics + optional client
CV/profile + config** into complete, evidence-backed research proposals in
**DOCX and PDF**. It does **not** depend on the legacy `app` package (GUI,
supervisor discovery, emailer, database), which continues to work unchanged.

## CLI

```bash
python -m proposal_engine run topics.yaml --config config.yaml \
    [--client <cv-file-or-dir>] [--force] [--topic <id>] [--evidence-only] [--out <dir>]
python -m proposal_engine approve <topic-id> [--out <dir>]
```

Example inputs live in [`proposal_engine/examples/`](examples/).

## Pipeline (per topic)

| Stage | Output artifacts |
|------|------------------|
| 0 Preflight | `run_log.json` (preflight block) |
| 1 Intake | `topic_manifest.json`, `extracted_profile.md` |
| 2 Search strategy | `search_strategy.md` |
| 3 Evidence build | `evidence_store.json`, `evidence_table.csv` |
| 4 Draft | `proposal_draft.md` |
| 5 Bibliography + audit | `references.json` (CSL-JSON), `citation_audit.csv` |
| 6 Render | `proposal.docx`, `proposal.pdf` |
| 7 Review | `review_checklist.md` |

## Keys / environment

- `OPENALEX_API_KEY` — **required** before any scholarly API call (basic keyless
  OpenAlex access exists, but this app requires a free key for reliable batch use).
- `ANTHROPIC_API_KEY` **or** `OPENAI_API_KEY` — required for drafting (Stage 4).
  Without it the engine runs **evidence-only** mode.
- `SEMANTIC_SCHOLAR_API_KEY`, `UNPAYWALL_EMAIL` — optional enrichment.

## Modes & guarantees

- **Evidence-only** (no model key): stages 0–3 only, deterministic keyword
  strategies and relevance notes; never fabricates evidence.
- **Resumability**: a stage is skipped only when its artifacts exist **and**
  `run_log.json` marks that stage `SUCCESS`. `--force` reruns everything.
- **Anti-hallucination**: sections cite only real evidence keys `[@key]`; the LLM
  never writes bibliography entries; unsupported future claims must be prefixed
  `Assumption:`; placeholders/TODOs are rejected; drafting has no silent fallback.
- **Rendering**: DOCX via Pandoc (`--citeproc`) when available, otherwise a
  built-in python-docx writer with citeproc-lite. PDF via LibreOffice `soffice`
  or, as fallback, docx2pdf/Word. If no PDF route works the render fails visibly.

## Tests

```bash
python -m pytest tests/proposal_engine -q
```

All tests are offline (recorded/handcrafted fixtures + a deterministic FakeLLM);
no live API calls.
