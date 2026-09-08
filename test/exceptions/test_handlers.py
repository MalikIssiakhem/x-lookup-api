import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.exceptions.handlers import register_exception_handlers


@pytest.fixture
def failing_client() -> TestClient:
    """A throwaway app whose routes raise, to exercise the handlers directly.

    The real app has no route that fails on demand — and it should not grow one
    just to be testable.

    `raise_server_exceptions=False` is what makes the catch-all handler
    observable: by default TestClient re-raises the server exception, so the test
    would assert on the exception and never see what the client receives.
    """
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("mongodb://user:sup3rs3cret@host:27017 is unreachable")

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail="I'm a teapot")

    @app.get("/silent")
    async def silent() -> None:
        raise HTTPException(status_code=418, detail="")

    return TestClient(app, raise_server_exceptions=False)


def test_an_unknown_route_returns_the_shared_error_envelope(
    client: TestClient,
) -> None:
    response = client.get("/there-is-no-such-route")

    assert response.status_code == 404
    assert response.json() == {"error": "not_found", "message": "Not Found"}


def test_an_unhandled_exception_returns_a_generic_internal_error(
    failing_client: TestClient,
) -> None:
    response = failing_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "message": "An unexpected error occurred.",
    }


def test_an_unhandled_exception_does_not_leak_the_cause_to_the_client(
    failing_client: TestClient,
) -> None:
    body = failing_client.get("/boom").text

    # The raised error carries a credential-bearing URI, the exact kind of thing
    # that must never reach a paying client's response body (CLAUDE.md §4).
    assert "sup3rs3cret" not in body
    assert "RuntimeError" not in body


def test_an_unhandled_exception_is_logged_once_with_its_stack_trace(
    failing_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("ERROR", logger="app.exceptions.handlers"):
        failing_client.get("/boom")

    records = [r for r in caplog.records if r.name == "app.exceptions.handlers"]
    assert len(records) == 1
    assert records[0].exc_info is not None


def test_an_unmapped_status_code_falls_back_to_a_generic_error_code(
    failing_client: TestClient,
) -> None:
    response = failing_client.get("/teapot")

    assert response.status_code == 418
    assert response.json() == {"error": "http_error", "message": "I'm a teapot"}


def test_an_http_error_without_a_detail_still_carries_a_message(
    failing_client: TestClient,
) -> None:
    response = failing_client.get("/silent")

    assert response.status_code == 418
    assert response.json() == {
        "error": "http_error",
        "message": "The request could not be served.",
    }
