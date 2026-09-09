import logging
from datetime import datetime, timezone

from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import PyMongoError

from app.config import settings
from app.exceptions.repository import (
    RepositoryDatabaseOperationError,
    RepositoryDataCorruptionError,
)
from app.models.sessions.session import XSessionInDB, XSessionStatus

logger = logging.getLogger(__name__)

# An allowlist, not a denylist. The same document also holds the account
# password, its recovery mailbox, that mailbox's password and the TOTP secret —
# everything needed to re-mint a session, and none of it needed to read a
# profile. Listing what we want (rather than excluding what we don't) means a
# secret field added to the document tomorrow stays out of this process by
# default instead of silently flowing in.
_USABLE_SESSION_FIELDS = {
    "_id": 0,
    "username": 1,
    "kind": 1,
    "auth_token": 1,
    "ct0": 1,
    "status": 1,
    "cooldown_until": 1,
}


class XSessionRepository:
    """Read-only access to the X account sessions collection.

    Read-only on purpose in this ticket: the writes (cooldown after error 88,
    eviction after 89/239/326) are driven by X's own responses, so they land
    with the client that reads those responses.

    Like every repository, it is the integrity boundary — it returns validated
    models, never raw dicts.
    """

    def __init__(self, mongo_db: AsyncDatabase[dict]) -> None:
        self._mongo_db = mongo_db
        self._sessions_collection = settings.X_SESSIONS_COLLECTION

    async def list_usable_sessions(self) -> list[XSessionInDB]:
        """Every session that can serve a request right now.

        The filter runs in Mongo rather than in Python: with a few thousand
        accounts, dragging the evicted and the cooling-down ones across the wire
        just to drop them costs bandwidth and holds their credentials in this
        process for no reason.

        A cooldown that has expired makes the account usable again on its own —
        no job has to flip anything back.
        """
        now = datetime.now(timezone.utc)
        query = {
            "status": XSessionStatus.ACTIVE.value,
            "$or": [
                {"cooldown_until": None},
                {"cooldown_until": {"$lte": now}},
            ],
        }

        try:
            docs = [
                doc
                async for doc in self._mongo_db[self._sessions_collection].find(
                    query, _USABLE_SESSION_FIELDS
                )
            ]
        except PyMongoError as e:
            logger.exception(f"Failed to read X sessions from MongoDB - {e}")
            raise RepositoryDatabaseOperationError(
                message="Could not read the X sessions",
                operation="list_usable_sessions",
                detail=str(e),
            ) from e

        try:
            return [XSessionInDB(**doc) for doc in docs]
        except ValidationError as e:
            # Deliberate deviation from the repo's `logger.exception(f"… - {e}")`
            # convention: a ValidationError carries the offending input, and here
            # the input is a live session — auth_token and ct0 included. Only the
            # field-level errors are kept, so a malformed document cannot leak a
            # credential into the logs (CLAUDE.md §4).
            sanitized = e.errors(include_input=False, include_url=False)
            logger.error(
                f"An X session document does not match the model - {sanitized}"
            )
            raise RepositoryDataCorruptionError(
                message="An X session document does not match the model",
                operation="list_usable_sessions",
                detail=str(sanitized),
            ) from e
