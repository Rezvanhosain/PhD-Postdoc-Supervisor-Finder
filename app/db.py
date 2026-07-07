"""SQLite storage layer. One connection per call keeps things simple and safe
for NiceGUI's async handlers."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (name TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL,           -- JSON candidate profile
    cv_filename TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, university TEXT, department TEXT, country TEXT,
    deadline TEXT, eligibility TEXT, description TEXT,
    source TEXT, source_url TEXT UNIQUE, date_accessed TEXT,
    review_status TEXT DEFAULT 'new'   -- new|reviewed|hidden
);
CREATE TABLE IF NOT EXISTS supervisors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, university TEXT, department TEXT, country TEXT,
    email TEXT, email_confidence TEXT DEFAULT 'unknown',  -- verified|scraped|unknown
    profile_url TEXT, research_areas TEXT,                 -- JSON list
    publications TEXT,                                     -- JSON list of dicts
    metrics TEXT,                                          -- JSON (citations, h-index...)
    supervises_phd TEXT DEFAULT 'unknown',
    source TEXT, source_url TEXT, date_accessed TEXT,
    external_id TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT,               -- 'position' | 'supervisor'
    target_id INTEGER,
    score REAL,
    reasons TEXT,            -- JSON: why, risks, email_angle, components
    confidence TEXT DEFAULT 'normal',   -- low|normal|high
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type TEXT,           -- cv|proposal|timeline|email
    title TEXT, path TEXT, related_kind TEXT, related_id INTEGER,
    meta TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT,             -- draft|sent|failed
    provider TEXT, recipient TEXT, subject TEXT, body TEXT,
    related_kind TEXT, related_id INTEGER,
    sent_at TEXT, created_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, authors TEXT, year TEXT, venue TEXT, doi TEXT, url TEXT,
    source_api TEXT, verified INTEGER DEFAULT 0,
    verification_note TEXT, document_id INTEGER
);
CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT,           -- scrape|api|reference|email|docgen|cv_parse|app|classify|supervisor
    message TEXT, detail TEXT, needs_review INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS fit_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    supervisor_id INTEGER DEFAULT 0,      -- 0 = opportunity-only fit
    score REAL,
    recommendation TEXT,                  -- strong|moderate|weak|avoid
    outreach_useful INTEGER DEFAULT 0,
    reasons TEXT,                         -- JSON: why, risks, components
    created_at TEXT,
    UNIQUE(position_id, supervisor_id)
);
CREATE TABLE IF NOT EXISTS applications (   -- lightweight tracker / CRM
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER DEFAULT 0,
    supervisor_id INTEGER DEFAULT 0,
    country TEXT DEFAULT '', university TEXT DEFAULT '',
    program TEXT DEFAULT '', faculty TEXT DEFAULT '',
    classification TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',  -- draft|ready|sent|reminder_due|replied|no_response|interview|rejected|admitted|archived
    sent_at TEXT DEFAULT '', follow_up_due TEXT DEFAULT '',
    last_activity TEXT DEFAULT '', notes TEXT DEFAULT '',
    attachments TEXT DEFAULT '[]',        -- JSON list of document paths/ids
    created_at TEXT,
    UNIQUE(position_id, supervisor_id)
);
"""

# v2 column additions to v1 tables (applied idempotently at startup)
MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "positions": [
        ("kind", "TEXT DEFAULT ''"),                    # phd|postdoc
        ("field", "TEXT DEFAULT ''"),
        ("funding", "TEXT DEFAULT ''"),
        ("official_url", "TEXT DEFAULT ''"),
        ("shortlisted", "INTEGER DEFAULT 0"),
        ("classification", "TEXT DEFAULT ''"),
        ("class_confidence", "REAL DEFAULT 0"),
        ("class_evidence", "TEXT DEFAULT ''"),
        ("class_source_url", "TEXT DEFAULT ''"),
        ("class_source_official", "INTEGER DEFAULT 0"),
        ("source_type", "TEXT DEFAULT ''"),             # ''|manual_url|manual_entry
        ("extraction_confidence", "REAL DEFAULT 0"),
        ("documents_required", "TEXT DEFAULT ''"),
    ],
    "supervisors": [
        ("title", "TEXT DEFAULT ''"),
        ("faculty", "TEXT DEFAULT ''"),
        ("source_type", "TEXT DEFAULT 'unofficial'"),   # official|unofficial
        ("position_id", "INTEGER DEFAULT 0"),           # opportunity that triggered discovery
    ],
    "email_log": [
        ("attachments", "TEXT DEFAULT '[]'"),           # JSON list of document paths
        ("position_id", "INTEGER DEFAULT 0"),
        ("supervisor_id", "INTEGER DEFAULT 0"),
    ],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols:
                if name not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


# ---- kv ----
def get_kv(name: str) -> Optional[str]:
    with conn() as c:
        row = c.execute("SELECT value FROM kv WHERE name=?", (name,)).fetchone()
        return row["value"] if row else None


def set_kv(name: str, value: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO kv(name,value) VALUES(?,?) "
                  "ON CONFLICT(name) DO UPDATE SET value=excluded.value", (name, value))


# ---- profile ----
def save_profile(data: dict, cv_filename: str | None = None) -> None:
    with conn() as c:
        c.execute("INSERT INTO profile(id,data,cv_filename,updated_at) VALUES(1,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET data=excluded.data, "
                  "cv_filename=COALESCE(excluded.cv_filename, profile.cv_filename), "
                  "updated_at=excluded.updated_at",
                  (json.dumps(data), cv_filename, now()))


def load_profile() -> Optional[dict]:
    with conn() as c:
        row = c.execute("SELECT data FROM profile WHERE id=1").fetchone()
        return json.loads(row["data"]) if row else None


# ---- generic helpers ----
def insert(table: str, **fields: Any) -> int:
    keys = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    with conn() as c:
        cur = c.execute(f"INSERT OR IGNORE INTO {table}({keys}) VALUES({marks})",
                        tuple(fields.values()))
        return cur.lastrowid or 0


def rows(sql: str, args: tuple = ()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def execute(sql: str, args: tuple = ()) -> None:
    with conn() as c:
        c.execute(sql, args)


init_db()  # schema is idempotent; guarantees tables exist for any entry point


def log_error(category: str, message: str, detail: str = "", needs_review: bool = False) -> None:
    insert("error_log", category=category, message=message[:500], detail=detail[:4000],
           needs_review=int(needs_review), created_at=now())
