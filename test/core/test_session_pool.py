import asyncio

import pytest

from app.core.session_pool import XSessionPool
from app.exceptions.repository import RepositoryDatabaseOperationError
from test.helpers import FakeSessionRepository, build_session


def build_pool(
    repository: FakeSessionRepository, refresh_interval_seconds: float = 0.01
) -> XSessionPool:
    return XSessionPool(
        session_repository=repository,  # type: ignore[arg-type]
        refresh_interval_seconds=refresh_interval_seconds,
    )


async def test_a_freshly_built_pool_holds_no_session() -> None:
    assert build_pool(FakeSessionRepository()).sessions == ()


async def test_loading_fills_the_pool_from_the_repository() -> None:
    repository = FakeSessionRepository([build_session(username="first")])
    pool = build_pool(repository)

    await pool.load()

    assert [session.username for session in pool.sessions] == ["first"]


async def test_a_successful_refresh_replaces_the_whole_snapshot() -> None:
    repository = FakeSessionRepository([build_session(username="before")])
    pool = build_pool(repository)
    await pool.load()

    repository.sessions = [build_session(username="after")]
    await pool.load()

    assert [session.username for session in pool.sessions] == ["after"]


async def test_a_failed_refresh_keeps_the_previously_loaded_sessions() -> None:
    repository = FakeSessionRepository([build_session(username="survivor")])
    pool = build_pool(repository)
    await pool.load()

    repository.error = RepositoryDatabaseOperationError(message="mongo is down")
    pool.start_refreshing()
    await _wait_until(lambda: repository.call_count >= 2)
    await pool.stop_refreshing()

    # A Mongo blip must not empty the pool: the API keeps serving on the
    # accounts it already had instead of 502-ing everything.
    assert [session.username for session in pool.sessions] == ["survivor"]


async def test_a_failed_refresh_does_not_kill_the_refresh_task() -> None:
    repository = FakeSessionRepository(
        [build_session()], error=RepositoryDatabaseOperationError(message="down")
    )
    pool = build_pool(repository)

    pool.start_refreshing()
    await _wait_until(lambda: repository.call_count >= 3)
    await pool.stop_refreshing()

    # Three attempts means the loop survived the first two failures. A task that
    # dies on the first error stops refreshing forever, silently.
    assert repository.call_count >= 3


async def test_the_refresh_task_is_cancelled_on_shutdown() -> None:
    repository = FakeSessionRepository([build_session()])
    pool = build_pool(repository)

    pool.start_refreshing()
    await pool.stop_refreshing()
    calls_at_shutdown = repository.call_count
    await asyncio.sleep(0.05)

    assert repository.call_count == calls_at_shutdown


async def test_stopping_a_pool_that_never_started_is_harmless() -> None:
    await build_pool(FakeSessionRepository()).stop_refreshing()


async def _wait_until(condition, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            pytest.fail("the condition was never met")
        await asyncio.sleep(0.005)


async def test_a_pool_that_never_loaded_reports_no_staleness() -> None:
    assert build_pool(FakeSessionRepository()).staleness_seconds is None


async def test_a_successful_load_resets_the_staleness() -> None:
    pool = build_pool(FakeSessionRepository([build_session()]))

    await pool.load()
    staleness = pool.staleness_seconds

    assert staleness is not None
    assert staleness < 1.0


async def test_a_failed_refresh_logs_how_old_the_snapshot_is(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeSessionRepository([build_session()])
    pool = build_pool(repository)
    await pool.load()
    repository.error = RepositoryDatabaseOperationError(message="mongo is down")

    with caplog.at_level("WARNING"):
        pool.start_refreshing()
        await _wait_until(lambda: repository.call_count >= 2)
        await pool.stop_refreshing()

    # Keeping the previous snapshot is right, but it has no time bound without
    # this: the log line is what says the pool is serving five-hour-old accounts.
    assert "last success" in caplog.text


async def test_a_successful_read_returning_nothing_empties_the_pool_loudly(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeSessionRepository([build_session()])
    pool = build_pool(repository)
    await pool.load()

    repository.sessions = []
    with caplog.at_level("ERROR"):
        await pool.load()

    # Emptying is the correct outcome — serving a stale snapshot would mean
    # hammering X with dead tokens — but doing it silently is not.
    assert pool.sessions == ()
    assert "empty after a successful read" in caplog.text


async def test_starting_the_refresh_twice_leaves_a_single_task() -> None:
    repository = FakeSessionRepository([build_session()])
    pool = build_pool(repository)

    pool.start_refreshing()
    pool.start_refreshing()
    await pool.stop_refreshing()
    calls_at_shutdown = repository.call_count
    await asyncio.sleep(0.05)

    # A second create_task would orphan the first, which would keep refreshing
    # forever with nobody holding a reference to cancel it.
    assert repository.call_count == calls_at_shutdown
