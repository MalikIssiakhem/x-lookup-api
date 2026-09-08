from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_exposes_only_a_status_field(client: TestClient) -> None:
    # Locked down now, before there is a session pool to leak: /health is the one
    # route exempted from the RapidAPI secret middleware, so anything it returns
    # is readable by a third party (CLAUDE.md §5). This test fails the day
    # someone adds an account count or a pool state to the payload.
    assert list(client.get("/health").json()) == ["status"]


def test_health_rejects_a_write_with_the_shared_error_envelope(
    client: TestClient,
) -> None:
    response = client.post("/health")

    assert response.status_code == 405
    assert response.json() == {
        "error": "method_not_allowed",
        "message": "Method Not Allowed",
    }
