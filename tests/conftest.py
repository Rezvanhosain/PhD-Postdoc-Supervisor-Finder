import os
import tempfile

# Isolate the app data dir before any app import
os.environ["PPSF_HOME"] = tempfile.mkdtemp(prefix="ppsf_test_")

import pytest  # noqa: E402

from app import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.init_db()
    yield
