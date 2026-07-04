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
