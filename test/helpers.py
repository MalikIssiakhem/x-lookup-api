from collections.abc import AsyncIterator, Iterable
from datetime import datetime

from pydantic import SecretStr

from app.models.sessions.session import XSessionInDB, XSessionStatus

# Every credential here is obviously fake and stays that way. Shared factories
# rather than payloads copy-pasted into each test: session documents grow, and a
# schema change has to be applied in one place (CLAUDE.md §6).
#
# The factories take explicit typed parameters rather than **overrides: a
# **kwargs of `object` unpacked into a validated model is untypeable, and would
# trade one convenience for a pile of type-ignores.

SessionDocument = dict[str, object]


def build_session_document(
    username: str = "dev_account",
    auth_token: str = "fake-auth-token",
    ct0: str = "fake-ct0",
    status: str = XSessionStatus.ACTIVE.value,
    cooldown_until: datetime | None = None,
) -> SessionDocument:
    """A Mongo document as the repository's projection returns it.

    Returned as a plain dict so a test can break it on purpose — dropping a
    field, or putting an impossible value in one — which is the whole point of
    the validation tests.
    """
    return {
        "username": username,
        "kind": "cookie",
        "auth_token": auth_token,
        "ct0": ct0,
        "status": status,
        "cooldown_until": cooldown_until,
    }


def build_session(
    username: str = "dev_account",
    auth_token: str = "fake-auth-token",
    ct0: str = "fake-ct0",
    status: XSessionStatus = XSessionStatus.ACTIVE,
    cooldown_until: datetime | None = None,
) -> XSessionInDB:
    """A validated session, as the pool holds it.

    The credentials are wrapped explicitly: pydantic would coerce a plain str at
    runtime, but the generated __init__ is typed on SecretStr and the checker is
    right to say so.
    """
    return XSessionInDB(
        username=username,
        auth_token=SecretStr(auth_token),
        ct0=SecretStr(ct0),
        status=status,
        cooldown_until=cooldown_until,
    )


class FakeCursor:
    """The async iterable pymongo's find() returns."""

    def __init__(self, documents: Iterable[SessionDocument]) -> None:
        self._documents = list(documents)

    async def __aiter__(self) -> AsyncIterator[SessionDocument]:
        for document in self._documents:
            yield document


class FakeCollection:
    def __init__(
        self,
        documents: Iterable[SessionDocument] = (),
        error: Exception | None = None,
    ) -> None:
        self._documents = list(documents)
        self._error = error
        # Recorded so a test can assert what was actually asked of Mongo — the
        # repository's job is the query it builds, not the data it gets back.
        self.received_query: dict[str, object] = {}
        self.received_projection: dict[str, object] = {}

    def find(
        self, query: dict[str, object], projection: dict[str, object]
    ) -> FakeCursor:
        self.received_query = query
        self.received_projection = projection
        if self._error is not None:
            raise self._error
        return FakeCursor(self._documents)


class FakeDatabase:
    def __init__(self, collection: FakeCollection) -> None:
        self._collection = collection

    def __getitem__(self, _name: str) -> FakeCollection:
        return self._collection


class FakeMongoAdmin:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.commands: list[str] = []

    async def command(self, name: str) -> dict[str, int]:
        self.commands.append(name)
        if self._error is not None:
            raise self._error
        return {"ok": 1}


class FakeMongoClient:
    """Enough of AsyncMongoClient for the lifespan: a ping and a database."""

    def __init__(self, ping_error: Exception | None = None) -> None:
        self.admin = FakeMongoAdmin(ping_error)

    def __getitem__(self, _name: str) -> object:
        return object()


class FakeSessionRepository:
    """Stands in for XSessionRepository in the pool and lifespan tests."""

    def __init__(
        self,
        sessions: Iterable[XSessionInDB] = (),
        error: Exception | None = None,
    ) -> None:
        self.sessions = list(sessions)
        self.error = error
        self.call_count = 0

    async def list_usable_sessions(self) -> list[XSessionInDB]:
        self.call_count += 1
        if self.error is not None:
            raise self.error
        return list(self.sessions)
