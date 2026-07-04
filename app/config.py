"""Configuration: .env file, UI-entered API keys, secure token storage.

Precedence: UI settings (stored in SQLite `settings` table) > environment / .env.
OAuth tokens are stored in the OS keychain via `keyring`; if that fails,
they are encrypted at rest with Fernet using a locally generated key file.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

APP_NAME = "PhD-Postdoc-Supervisor-Finder"
APP_DIR = Path(os.environ.get("PPSF_HOME", Path.home() / ".phd_finder"))
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "app.db"
CACHE_DIR = APP_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = APP_DIR / "generated"
OUTPUT_DIR.mkdir(exist_ok=True)
LOG_FILE = APP_DIR / "app.log"

load_dotenv()  # project .env
load_dotenv(APP_DIR / ".env")  # user-level .env

KEY_NAMES = [
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "SEMANTIC_SCHOLAR_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "MS_CLIENT_ID",
    "MS_TENANT_ID",
    "CONTACT_EMAIL",  # used in polite API User-Agent headers
]


def get_setting(name: str) -> Optional[str]:
    """UI-stored setting first, then environment."""
    from app import db  # late import to avoid cycles

    val = db.get_kv(name)
    if val:
        return val
    return os.environ.get(name) or None


def set_setting(name: str, value: str) -> None:
    from app import db

    db.set_kv(name, value)


# ---------------- secure token storage ----------------

_SERVICE = APP_NAME


def _fernet():
    from cryptography.fernet import Fernet

    key_file = APP_DIR / ".secret.key"
    if not key_file.exists():
        key_file.write_bytes(Fernet.generate_key())
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    return Fernet(key_file.read_bytes())


def store_secret(name: str, value: str) -> None:
    try:
        import keyring

        keyring.set_password(_SERVICE, name, value)
        return
    except Exception:
        pass
    enc = _fernet().encrypt(value.encode())
    (APP_DIR / f".{name}.enc").write_bytes(enc)


def load_secret(name: str) -> Optional[str]:
    try:
        import keyring

        val = keyring.get_password(_SERVICE, name)
        if val:
            return val
    except Exception:
        pass
    f = APP_DIR / f".{name}.enc"
    if f.exists():
        try:
            return _fernet().decrypt(f.read_bytes()).decode()
        except Exception:
            return None
    return None


def delete_secret(name: str) -> None:
    try:
        import keyring

        keyring.delete_password(_SERVICE, name)
    except Exception:
        pass
    f = APP_DIR / f".{name}.enc"
    if f.exists():
        f.unlink()


def has_llm() -> bool:
    return bool(get_setting("OPENAI_API_KEY"))
