import os

# Must run before anything imports app.config: the datastore settings have no
# default, so importing the app without them would fail at collection time.
# These values are never connected to — every test fakes the repository — they
# only let Settings() build, locally and in CI, with no .env in sight.
os.environ.setdefault("X_SESSIONS_MONGODB_URL", "mongodb://localhost:27017")
os.environ.setdefault("X_SESSIONS_MONGODB_DB_NAME", "x_sessions")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    """The real application under test.

    Not used as a context manager, so the lifespan does not run and no test
    accidentally reaches for Mongo. The lifespan has its own tests, which drive
    it explicitly with fakes.
    """
    return TestClient(app)
