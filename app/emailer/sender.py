"""Safe sending layer: manual review required, daily send limit, full logging.
Mass-mailing is intentionally not supported — one email at a time."""
from __future__ import annotations

from datetime import date

from app.db import execute, insert, log_error, now, rows
from app.emailer import gmail_oauth, outlook_oauth
from app.config import get_setting

DEFAULT_DAILY_LIMIT = 10


def daily_limit() -> int:
    try:
        return int(get_setting("DAILY_SEND_LIMIT") or DEFAULT_DAILY_LIMIT)
    except ValueError:
        return DEFAULT_DAILY_LIMIT


def sent_today() -> int:
    today = date.today().isoformat()
    r = rows("SELECT COUNT(*) AS n FROM email_log WHERE status='sent' AND sent_at LIKE ?",
             (today + "%",))
    return r[0]["n"] if r else 0


def send_draft(draft_id: int, provider: str) -> tuple[bool, str]:
    """Send a single reviewed draft. Returns (ok, message)."""
    drafts = rows("SELECT * FROM email_log WHERE id=? AND status='draft'", (draft_id,))
    if not drafts:
        return False, "Draft not found (was it already sent?)."
    d = drafts[0]
    if not d["recipient"]:
        return False, "No recipient email on this draft — add one first."
    if sent_today() >= daily_limit():
        return False, (f"Daily send limit ({daily_limit()}) reached. This protects you "
                       "from accidentally spamming academics. Try again tomorrow or "
                       "raise the limit in Settings.")
    try:
        mod = gmail_oauth if provider == "gmail" else outlook_oauth
        ok = mod.send(d["recipient"], d["subject"], d["body"])
    except Exception as e:
        log_error("email", f"Send failed to {d['recipient']}", str(e))
        execute("UPDATE email_log SET status='failed', error=? WHERE id=?", (str(e)[:500], draft_id))
        return False, f"Send failed: {e}"
    if ok:
        execute("UPDATE email_log SET status='sent', provider=?, sent_at=? WHERE id=?",
                (provider, now(), draft_id))
        return True, "Sent."
    execute("UPDATE email_log SET status='failed' WHERE id=?", (draft_id,))
    return False, "Provider rejected the message — see Logs."
