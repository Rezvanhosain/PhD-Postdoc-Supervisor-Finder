# Architecture

Single local Python process. NiceGUI serves the UI at `127.0.0.1:8765` and opens the
default browser; no data leaves the machine except explicit API calls.

```
┌─────────────────────────── Desktop shortcut (pythonw -m app.main) ───────────────────────────┐
│                                                                                              │
│  NiceGUI UI (app/main.py)                                                                    │
│  Dashboard · Upload CV · Interests · Positions · Supervisors · Matches ·                     │
│  Documents · Outreach · Settings · Logs/Review                                               │
│        │                                                                                     │
│        ▼                                                                                     │
│  Core modules                                                                                │
│  ├─ cv_parser.py        PDF/DOCX → profile dict + warnings                                   │
│  ├─ matching.py         TF-IDF (+optional embeddings) explainable scoring                    │
│  ├─ references.py       verified-only citations, 4 styles, audit tables                      │
│  ├─ docgen/             CV / proposal / timeline / email → DOCX + PDF                        │
│  ├─ emailer/            Gmail OAuth · Outlook MSAL · safe sender (limits, logs)              │
│  └─ llm.py              optional OpenAI-compatible rewording (guard prompt)                  │
│        │                                                                                     │
│        ▼                                                                                     │
│  sources/http.py — politeness layer: robots.txt, 1.5s/host throttle, 24h disk cache          │
│  ├─ openalex.py · semantic_scholar.py · crossref.py     (official APIs)                      │
│  └─ positions.py  EURAXESS / FindAPhD / AcademicPositions / THE (best-effort HTML)           │
│        │                                                                                     │
│        ▼                                                                                     │
│  SQLite (~/.phd_finder/app.db): profile, positions, supervisors, matches,                    │
│  documents, email_log, citations, error_log, kv settings                                     │
│  Secrets: OS keychain via `keyring`, Fernet-encrypted file fallback                          │
│  Files:  ~/.phd_finder/generated/ (DOCX/PDF/audit), cache/, app.log                          │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Key decisions

- **NiceGUI over Electron/Tauri**: pure-Python, no Node toolchain, trivially packaged with a
  venv + shortcut; `pythonw.exe` gives a terminal-free launch on Windows.
- **SQLite, one connection per operation**: safe with NiceGUI's async handlers, zero setup.
- **Explainable matching first, embeddings second**: TF-IDF works offline; embeddings blend
  in automatically when a key exists. Component scores are stored with every match.
- **Verified-references pipeline**: generation code *cannot* emit a citation that didn't come
  from a metadata API; verification status is persisted per citation and exported per document.
- **All failure paths write to `error_log`** with a `needs_review` flag that feeds the
  Logs / Manual Review page.

---

# v2 architecture (workflow-chained)

```
Step 1 Profile        app/cv_parser.py (v1, reused)
Step 2 Search         app/sources/positions.py  + app/europe.py (Europe-only filters)
Step 3 Classify       app/classify.py            rule-based, evidence-preserving,
                                                 official-source-aware (official wins)
Step 4 Supervisors    app/sources/university.py  institution-constrained: OpenAlex
                                                 institution filter + official staff /
                                                 faculty / doctoral-school page mining
Step 5 Fit            app/fit.py                 shortlist-only scoring of
                                                 (opportunity, supervisor?) pairs
Step 6 Documents      app/docgen/bundles.py      bundle A/B/C per admission path;
                                                 reuses v1 generators + verified refs
Step 7 Outreach       app/emailer/* (v1, reused) drafts carry attachments + links to
                                                 position/supervisor; sending advances
                                                 the tracker
Step 8 Tracker        app/tracker.py             applications table, statuses,
                                                 14-day follow-up reminders
```

State chaining lives in SQLite (`positions.shortlisted`, `supervisors.position_id`,
`fit_scores`, `applications`, `email_log.attachments/position_id/supervisor_id`).
Schema upgrades are applied idempotently at startup (`db.MIGRATIONS`).
