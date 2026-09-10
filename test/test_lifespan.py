import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

import app.main
from app.exceptions.sessions import EmptySessionPoolError
from app.main import app as api
from test.helpers import FakeMongoClient, FakeSessionRepository, build_session


@pytest.fixture
def wired_lifespan(monkeypatch: pytest.MonkeyPatch):
    """Drive the lifespan against fakes — no Mongo is ever contacted.

    Returns a function the test calls with the sessions it wants the repository
    to hold, and with an optional ping failure.
    """

    def wire(
        sessions=(), ping_error: Exception | None = None
    ) -> tuple[FakeMongoClient, FakeSessionRepository]:
        mongo_client = FakeMongoClient(ping_error=ping_error)
        repository = FakeSessionRepository(sessions)
        closed: list[bool] = []

        async def fake_close() -> None:
            closed.append(True)

        monkeypatch.setattr(app.main, "get_x_sessions_client", lambda: mongo_client)
        monkeypatch.setattr(app.main, "XSessionRepository", lambda mongo_db: repository)
        monkeypatch.setattr(app.main, "close_mongo_clients", fake_close)
        return mongo_client, repository

    return wire


def test_the_lifespan_refuses_to_boot_when_the_session_pool_is_empty(
    wired_lifespan,
) -> None:
    wired_lifespan(sessions=())

    # An API with no session is not degraded, it is incapable: better a
    # container that refuses to start than one that is up and 502-ing.
    with pytest.raises(EmptySessionPoolError):
        with TestClient(api):
            pass


def test_the_lifespan_refuses_to_boot_when_the_session_store_is_unreachable(
    wired_lifespan,
) -> None:
    wired_lifespan(
        sessions=[build_session()],
        ping_error=ServerSelectionTimeoutError("no reachable servers"),
    )

    with pytest.raises(ServerSelectionTimeoutError):
        with TestClient(api):
            pass


def test_the_lifespan_pings_mongo_before_loading_the_pool(wired_lifespan) -> None:
    mongo_client, repository = wired_lifespan(sessions=[build_session()])

    with TestClient(api):
        pass

    # The ping is what turns an unreachable datastore into a failed boot rather
    # than a 500 on every request.
    assert mongo_client.admin.commands == ["ping"]
    assert repository.call_count == 1


def test_the_lifespan_exposes_the_loaded_pool_on_the_application_state(
    wired_lifespan,
) -> None:
    wired_lifespan(sessions=[build_session(username="loaded")])

    with TestClient(api):
        # Read from the app object itself: TestClient.app is typed as a bare ASGI
        # callable, and reaching through it for .state is a type error.
        pool = api.state.x_session_pool

        assert [session.username for session in pool.sessions] == ["loaded"]


def test_the_api_still_serves_health_once_booted(wired_lifespan) -> None:
    wired_lifespan(sessions=[build_session()])

    with TestClient(api) as client:
        assert client.get("/health").json() == {"status": "ok"}
