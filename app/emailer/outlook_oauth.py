"""Outlook / Microsoft 365 send via MSAL device-code flow + Microsoft Graph.

The user registers a free app in Entra ID (public client, Mail.Send delegated
permission) and enters MS_CLIENT_ID (and optionally MS_TENANT_ID) in Settings.
Tokens live in the MSAL cache stored via the secure secret store."""
from __future__ import annotations

from typing import Callable, Optional

import msal

from app.config import delete_secret, get_setting, load_secret, store_secret
from app.db import log_error

SCOPES = ["Mail.Send"]
TOKEN_NAME = "outlook_msal_cache"


def _app() -> msal.PublicClientApplication:
    client_id = get_setting("MS_CLIENT_ID")
    if not client_id:
        raise RuntimeError("Set MS_CLIENT_ID in Settings first.")
    tenant = get_setting("MS_TENANT_ID") or "common"
    cache = msal.SerializableTokenCache()
    raw = load_secret(TOKEN_NAME)
    if raw:
        cache.deserialize(raw)
    app = msal.PublicClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=cache)
    app._ppsf_cache = cache  # keep a handle for persisting
    return app


def _persist(app: msal.PublicClientApplication) -> None:
    if app._ppsf_cache.has_state_changed:
        store_secret(TOKEN_NAME, app._ppsf_cache.serialize())


def is_connected() -> bool:
    try:
        app = _app()
        return bool(app.get_accounts())
    except Exception:
        return False


def disconnect() -> None:
    delete_secret(TOKEN_NAME)


def connect(show_code: Callable[[str], None]) -> bool:
    """Device-code flow. `show_code` receives the user instructions to display."""
    app = _app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Device flow failed: {flow.get('error_description', flow)}")
    show_code(flow["message"])
    result = app.acquire_token_by_device_flow(flow)  # blocks until user completes
    _persist(app)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", "Authentication failed."))
    return True


def _token() -> Optional[str]:
    app = _app()
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    _persist(app)
    return result.get("access_token") if result else None


def send(to: str, subject: str, body: str, attachments: Optional[list[str]] = None) -> bool:
    token = _token()
    if not token:
        raise RuntimeError("Outlook is not connected. Connect it in Settings > Email accounts.")
    import base64
    from pathlib import Path

    import httpx

    atts = []
    for path in attachments or []:
        p = Path(path)
        atts.append({"@odata.type": "#microsoft.graph.fileAttachment",
                     "name": p.name,
                     "contentBytes": base64.b64encode(p.read_bytes()).decode()})
    payload = {"message": {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": to}}],
        "attachments": atts}}
    resp = httpx.post("https://graph.microsoft.com/v1.0/me/sendMail",
                      headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=60)
    if resp.status_code >= 300:
        log_error("email", f"Outlook send failed ({resp.status_code})", resp.text[:500])
        return False
    return True
