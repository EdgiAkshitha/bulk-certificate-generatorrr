import os
import tempfile

_TMP_DB = os.path.join(tempfile.mkdtemp(prefix="certtest_"), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"  # must be set before app import

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    """Fresh tables and a fresh storage directory for every test."""
    settings.storage_dir = tmp_path / "certs"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    # TestClient runs BackgroundTasks before returning the response, so after a
    # POST the job has already been processed - tests stay deterministic.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_payload():
    def _make(recipients=None, **overrides):
        payload = {
            "course_name": "Python for Backend Engineers",
            "issuer_name": "AEREO Academy",
            "issue_date": "2026-10-01",
            "recipients": recipients
            if recipients is not None
            else [{"name": "Asha Rao", "email": "asha@example.com"}, {"name": "Ben Carter"}],
        }
        payload.update(overrides)
        return payload

    return _make
