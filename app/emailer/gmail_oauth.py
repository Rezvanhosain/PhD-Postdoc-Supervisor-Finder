"""Gmail send via OAuth 2.0 (google-auth-oauthlib, InstalledAppFlow).

The user supplies their own OAuth client (GOOGLE_CLIENT_ID/SECRET from Google
Cloud Console, 'Desktop app' type). Tokens are stored via app.config
(OS keychain, or encrypted file fallback) — never in plaintext or logs."""
from __future__ import annotations

import base64
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from app.config import delete_secret, get_setting, load_secret, store_secret
from app.db import log_error

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_NAME = "gmail_token"


def is_connected() -> bool:
    return load_secret(TOKEN_NAME) is not None


def disconnect() -> None:
    delete_secret(TOKEN_NAME)


def connect() -> bool:
    """Run the local-server OAuth flow (opens the user's browser)."""
    client_id = get_setting("GOOGLE_CLIENT_ID")
    client_secret = get_setting("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Settings first.")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config({
        "installed": {"client_id": client_id, "client_secret": client_secret,
                      "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                      "token_uri": "https://oauth2.googleapis.com/token",
                      "redirect_uris": ["http://localhost"]}}, SCOPES)
    creds = flow.run_local_server(port=0)
    store_secret(TOKEN_NAME, creds.to_json())
    return True


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    raw = load_secret(TOKEN_NAME)
    if not raw:
        return None
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store_secret(TOKEN_NAME, creds.to_json())
    return creds


def send(to: str, subject: str, body: str, attachments: Optional[list[str]] = None) -> bool:
    creds = _credentials()
    if not creds:
        raise RuntimeError("Gmail is not connected. Connect it in Settings > Email accounts.")
    import httpx

    msg = MIMEMultipart()
    msg["to"], msg["subject"] = to, subject
    msg.attach(MIMEText(body, "plain"))
    for path in attachments or []:
        from email.mime.application import MIMEApplication
        from pathlib import Path

        p = Path(path)
        part = MIMEApplication(p.read_bytes(), Name=p.name)
        part["Content-Disposition"] = f'attachment; filename="{p.name}"'
        msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resp = httpx.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                      headers={"Authorization": f"Bearer {creds.token}"},
                      json={"raw": raw}, timeout=60)
    if resp.status_code >= 300:
        log_error("email", f"Gmail send failed ({resp.status_code})", resp.text[:500])
        return False
    return True
