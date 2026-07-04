"""Application logging. Never log secrets: a filter redacts anything that
looks like a token or API key."""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from app.config import LOG_FILE

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{10,}|Bearer\s+\S+|ya29\.\S+|eyJ[A-Za-z0-9_\-]{20,}\S*)")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _SECRET_RE.sub("[REDACTED]", str(record.msg))
        if record.args:
            record.args = tuple(_SECRET_RE.sub("[REDACTED]", str(a)) for a in record.args)
        return True


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("ppsf")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(RedactFilter())
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.addFilter(RedactFilter())
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


log = setup_logging()
