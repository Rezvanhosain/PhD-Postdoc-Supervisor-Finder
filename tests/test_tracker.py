"""Tracker: lifecycle, notes, 14-day reminders."""
from datetime import date, timedelta

import pytest

from app import db
from app.tracker import (REMINDER_DAYS, add_note, ensure_application,
                         refresh_reminders, set_status)


def _pos() -> dict:
    pid = db.insert("positions", title="PhD X", university="Uni Y", country="HU",
                    classification="supervisor_required", source="t",
                    source_url=f"https://x/{__import__('uuid').uuid4()}")
    return db.rows("SELECT * FROM positions WHERE id=?", (pid,))[0]


def test_ensure_application_idempotent():
    pos = _pos()
    a1 = ensure_application(pos, None, attachments=["cv.docx"])
    a2 = ensure_application(pos, None, attachments=["email.docx"])
    assert a1 == a2
    row = db.rows("SELECT * FROM applications WHERE id=?", (a1,))[0]
    assert "cv.docx" in row["attachments"] and "email.docx" in row["attachments"]
    assert row["classification"] == "supervisor_required"


def test_sent_sets_follow_up():
    pos = _pos()
    aid = ensure_application(pos)
    set_status(aid, "sent")
    row = db.rows("SELECT * FROM applications WHERE id=?", (aid,))[0]
    expected = (date.today() + timedelta(days=REMINDER_DAYS)).isoformat()
    assert row["follow_up_due"] == expected
    assert row["sent_at"]


def test_reminder_transition():
    pos = _pos()
    aid = ensure_application(pos)
    set_status(aid, "sent")
    db.execute("UPDATE applications SET follow_up_due=? WHERE id=?",
               ((date.today() - timedelta(days=1)).isoformat(), aid))
    moved = refresh_reminders()
    assert moved >= 1
    assert db.rows("SELECT status FROM applications WHERE id=?", (aid,))[0]["status"] \
        == "reminder_due"


def test_invalid_status_rejected():
    pos = _pos()
    aid = ensure_application(pos)
    with pytest.raises(ValueError):
        set_status(aid, "nonsense")


def test_notes_are_appended():
    pos = _pos()
    aid = ensure_application(pos)
    add_note(aid, "first")
    add_note(aid, "second")
    notes = db.rows("SELECT notes FROM applications WHERE id=?", (aid,))[0]["notes"]
    assert "first" in notes and "second" in notes
