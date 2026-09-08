import pytest
from fastapi.testclient import TestClient

from app.main import app

# Every setting has a default today, so the tests need no environment at all.
# When the first required value lands (the Mongo/Redis URLs, ticket 3), the
# `os.environ.setdefault(...)` block goes here so `pytest` keeps running without
# a populated .env, locally and in CI.


@pytest.fixture
def client() -> TestClient:
    """The real application under test."""
    return TestClient(app)
