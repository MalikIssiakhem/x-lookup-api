from pymongo import AsyncMongoClient

from app.config import settings

# Module-level singleton: one client per Mongo per process. AsyncMongoClient is
# not thread-safe and binds to a single event loop — exactly FastAPI's model.
# Built lazily and reused, so every caller shares the same pooled connections
# instead of opening its own. tz_aware keeps datetimes UTC-aware, which matters
# for the cooldown comparisons. Parametrized with the document type (dict) so
# reads return a proper mapping and XSessionInDB(**doc) type-checks.
_x_sessions_client: AsyncMongoClient[dict] | None = None


def get_x_sessions_client() -> AsyncMongoClient[dict]:
    global _x_sessions_client
    client = _x_sessions_client
    if client is None:
        client = AsyncMongoClient(
            settings.X_SESSIONS_MONGODB_URL,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            tz_aware=True,
            appname="x-lookup-api",
        )
        _x_sessions_client = client
    return client


async def close_mongo_clients() -> None:
    global _x_sessions_client
    if _x_sessions_client is not None:
        await _x_sessions_client.close()
    _x_sessions_client = None
