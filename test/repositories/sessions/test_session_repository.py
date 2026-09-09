from datetime import datetime, timezone

import pytest
from pymongo.errors import PyMongoError

from app.exceptions.repository import (
    RepositoryDatabaseOperationError,
    RepositoryDataCorruptionError,
)
from app.models.sessions.session import XSessionInDB, XSessionStatus
from app.repositories.sessions.session_repository import XSessionRepository
from test.helpers import FakeCollection, FakeDatabase, build_session_document


def build_repository(collection: FakeCollection) -> XSessionRepository:
    return XSessionRepository(mongo_db=FakeDatabase(collection))  # type: ignore[arg-type]


async def test_the_repository_returns_validated_models_never_raw_documents() -> None:
    collection = FakeCollection([build_session_document(username="first")])

    sessions = await build_repository(collection).list_usable_sessions()

    assert [type(session) for session in sessions] == [XSessionInDB]
    assert sessions[0].username == "first"


async def test_the_repository_asks_mongo_only_for_the_fields_the_pool_needs() -> None:
    collection = FakeCollection()

    await build_repository(collection).list_usable_sessions()

    # An allowlist: the account password, its mailbox and the TOTP secret live
    # in the same document and must never enter this process.
    assert collection.received_projection == {
        "_id": 0,
        "username": 1,
        "kind": 1,
        "auth_token": 1,
        "ct0": 1,
        "status": 1,
        "cooldown_until": 1,
    }


async def test_the_repository_leaves_out_evicted_and_cooling_down_sessions() -> None:
    collection = FakeCollection()

    await build_repository(collection).list_usable_sessions()

    query = collection.received_query
    assert query["status"] == XSessionStatus.ACTIVE.value
    # The filter runs in Mongo, not in Python: unusable accounts never cross the
    # wire, so their credentials are never held here.
    cooldown_clauses = query["$or"]
    assert isinstance(cooldown_clauses, list)
    # A cooldown that has expired makes the account usable again on its own —
    # nothing has to flip a flag back.
    assert {"cooldown_until": None} in cooldown_clauses
    expiry_clause = next(
        clause for clause in cooldown_clauses if clause != {"cooldown_until": None}
    )
    assert expiry_clause["cooldown_until"]["$lte"] <= datetime.now(timezone.utc)


async def test_a_mongo_failure_becomes_a_repository_database_operation_error() -> None:
    collection = FakeCollection(error=PyMongoError("connection refused"))

    with pytest.raises(RepositoryDatabaseOperationError):
        await build_repository(collection).list_usable_sessions()


async def test_a_corrupted_session_document_becomes_a_data_corruption_error() -> None:
    broken = build_session_document()
    del broken["auth_token"]
    collection = FakeCollection([broken])

    with pytest.raises(RepositoryDataCorruptionError):
        await build_repository(collection).list_usable_sessions()


async def test_a_corrupted_session_document_is_logged_without_its_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = build_session_document(ct0="leaky-ct0")
    broken["status"] = "not-a-status"
    collection = FakeCollection([broken])

    with caplog.at_level("ERROR"):
        with pytest.raises(RepositoryDataCorruptionError) as raised:
            await build_repository(collection).list_usable_sessions()

    # A pydantic ValidationError carries the offending input, and here that
    # input is a live session. Neither the log nor the raised error may repeat
    # it (CLAUDE.md §4).
    assert "leaky-ct0" not in caplog.text
    assert "leaky-ct0" not in str(raised.value)


async def test_the_repository_only_asks_mongo_for_cookie_sessions() -> None:
    collection = FakeCollection()

    await build_repository(collection).list_usable_sessions()

    # The cheapest guard against the most likely corruption: an account of a
    # kind this reader cannot parse never reaches the validation at all.
    assert collection.received_query["kind"] == "cookie"


async def test_the_requested_kind_is_one_the_model_accepts() -> None:
    collection = FakeCollection()
    await build_repository(collection).list_usable_sessions()
    requested_kind = collection.received_query["kind"]

    # Drift guard: the day the model learns a second kind, asking Mongo for a
    # value it no longer accepts would silently return an empty pool.
    document = build_session_document()
    document["kind"] = requested_kind

    assert XSessionInDB(**document).kind == requested_kind  # type: ignore[bad-argument-type]


async def test_a_single_invalid_document_does_not_discard_the_valid_ones() -> None:
    broken = build_session_document(username="broken")
    del broken["auth_token"]
    collection = FakeCollection(
        [
            build_session_document(username="first"),
            broken,
            build_session_document(username="third"),
        ]
    )

    sessions = await build_repository(collection).list_usable_sessions()

    # One rotten row must not take the other 2999 accounts down with it — and
    # it would come back on every single read, so this would be permanent.
    assert [session.username for session in sessions] == ["first", "third"]


async def test_skipping_an_invalid_document_is_logged_with_the_counts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = build_session_document(username="broken")
    del broken["auth_token"]
    collection = FakeCollection([build_session_document(), broken])

    with caplog.at_level("ERROR"):
        await build_repository(collection).list_usable_sessions()

    # Tolerance is silent by nature; this line is the only thing standing
    # between a pool shrinking to nothing and nobody noticing.
    assert "Skipped 1 invalid X session(s) out of 2" in caplog.text


async def test_every_document_being_invalid_is_a_data_corruption_error() -> None:
    broken = build_session_document()
    del broken["auth_token"]
    collection = FakeCollection([broken, dict(broken)])

    # Nothing validating means the model no longer matches the schema. That has
    # to be loud, not reported as "no session available".
    with pytest.raises(RepositoryDataCorruptionError):
        await build_repository(collection).list_usable_sessions()


async def test_an_empty_collection_is_not_a_corruption_error() -> None:
    sessions = await build_repository(FakeCollection([])).list_usable_sessions()

    # No document at all is a legitimate state (a brand new deployment); the
    # lifespan is what turns it into a refused boot.
    assert sessions == []
