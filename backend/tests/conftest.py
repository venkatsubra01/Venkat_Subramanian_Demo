import os
import tempfile
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="internal-tools-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmpdir) / 'test.db'}"
os.environ["SESSION_SECRET"] = "test-secret-not-for-real-use-123456"
os.environ["ALLOWED_ORIGINS"] = "http://127.0.0.1:5173"
os.environ["ATTACHMENTS_DIR"] = str(Path(_tmpdir) / "attachments")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.chargebacks import clear_attachment_files  # noqa: E402
from app.db import Base, SessionLocal, create_tables, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    clear_attachment_files()
    create_tables()
    with SessionLocal() as db:
        seed(db)
    yield


def _client_as(identity: str | None) -> TestClient:
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    if identity is not None:
        response = client.post("/api/demo/session", json={"identity": identity})
        assert response.status_code == 200
    return client


@pytest.fixture
def anon() -> TestClient:
    return _client_as(None)


@pytest.fixture
def viewer() -> TestClient:
    return _client_as("viewer")


@pytest.fixture
def reviewer() -> TestClient:
    return _client_as("reviewer")
