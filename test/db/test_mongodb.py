import pytest

from app.db.mongodb import close_mongo_clients, get_x_sessions_client


@pytest.fixture(autouse=True)
async def release_the_module_singleton():
    """Reset the module-level client around every test.

    Building an AsyncMongoClient opens no socket — pymongo connects lazily — so
    these tests never touch a real Mongo. But the singleton would otherwise leak
    from one test into the next.
    """
    await close_mongo_clients()
    yield
    await close_mongo_clients()


async def test_the_mongo_client_is_built_once_and_reused() -> None:
    # One client per process: every caller shares the same pooled connections
    # instead of opening its own.
    assert get_x_sessions_client() is get_x_sessions_client()


async def test_closing_lets_a_later_call_build_a_fresh_client() -> None:
    first = get_x_sessions_client()

    await close_mongo_clients()

    assert get_x_sessions_client() is not first


async def test_closing_twice_is_harmless() -> None:
    get_x_sessions_client()

    await close_mongo_clients()
    await close_mongo_clients()


async def test_closing_before_anything_was_built_is_harmless() -> None:
    await close_mongo_clients()
