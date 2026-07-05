"""Lightweight application tracker / CRM (workflow step 8).

One row per (opportunity, supervisor) pair being pursued. Statuses follow the
real lifecycle; a 14-day follow-up reminder is computed automatically after
sending."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from app.db import execute, insert, now, rows

STATUSES = ["draft", "ready", "sent", "reminder_due", "replied", "no_response",
            "interview", "rejected", "admitted", "archived"]

REMINDER_DAYS = 14


def ensure_application(pos: dict, sup: dict | None = None,
                       attachments: list[str] | None = None) -> int:
    """Create (or update attachments of) a tracker row for this pair."""
    sid = (sup or {}).get("id", 0) or 0
    existing = rows("SELECT * FROM applications WHERE position_id=? AND supervisor_id=?",
                    (pos.get("id", 0), sid))
    if existing:
        if attachments:
            old = json.loads(existing[0].get("attachments") or "[]")
            merged = old + [a for a in attachments if a not in old]
            execute("UPDATE applications SET attachments=?, last_activity=? WHERE id=?",
                    (json.dumps(merged), now(), existing[0]["id"]))
        return existing[0]["id"]
    return insert(
        "applications",
        position_id=pos.get("id", 0), supervisor_id=sid,
        country=pos.get("country", ""), university=pos.get("university", ""),
        program=pos.get("title", ""), faculty=(sup or {}).get("faculty", "") or
        pos.get("department", ""),
        classification=pos.get("classification", ""),
        status="draft", attachments=json.dumps(attachments or []),
        last_activity=now(), created_at=now())


def set_status(app_id: int, status: str, note: str = "") -> None:
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    fields = {"status": status, "last_activity": now()}
    if status == "sent":
        fields["sent_at"] = now()
        fields["follow_up_due"] = (date.today() + timedelta(days=REMINDER_DAYS)).isoformat()
    sets = ", ".join(f"{k}=?" for k in fields)
    execute(f"UPDATE applications SET {sets} WHERE id=?", (*fields.values(), app_id))
    if note:
        add_note(app_id, note)


def add_note(app_id: int, note: str) -> None:
    got = rows("SELECT notes FROM applications WHERE id=?", (app_id,))
    if not got:
        return
    stamp = datetime.now().strftime("%Y-%m-%d")
    new = (got[0]["notes"] + "\n" if got[0]["notes"] else "") + f"[{stamp}] {note}"
    execute("UPDATE applications SET notes=?, last_activity=? WHERE id=?",
            (new, now(), app_id))


def refresh_reminders() -> int:
    """Move 'sent' rows past their follow-up date to 'reminder_due'."""
    today = date.today().isoformat()
    due = rows("SELECT id FROM applications WHERE status='sent' "
               "AND follow_up_due!='' AND follow_up_due<=?", (today,))
    for r in due:
        execute("UPDATE applications SET status='reminder_due', last_activity=? WHERE id=?",
                (now(), r["id"]))
    return len(due)


def mark_sent_from_email(email_id: int) -> None:
    """When an outreach email is sent, advance the matching tracker row."""
    em = rows("SELECT * FROM email_log WHERE id=?", (email_id,))
    if not em:
        return
    e = em[0]
    apps = rows("SELECT id FROM applications WHERE position_id=? AND supervisor_id=?",
                (e.get("position_id", 0) or 0, e.get("supervisor_id", 0) or 0))
    for a in apps:
        set_status(a["id"], "sent", note=f"Outreach email sent to {e.get('recipient','')}.")


def overview() -> list[dict]:
    refresh_reminders()
    apps = rows(
        "SELECT a.*, s.name AS supervisor_name FROM applications a "
        "LEFT JOIN supervisors s ON s.id=a.supervisor_id "
        "WHERE a.status!='archived' ORDER BY a.last_activity DESC")
    return apps
