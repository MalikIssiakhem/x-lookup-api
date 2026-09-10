import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.core.session_pool import XSessionPool
from app.db.mongodb import close_mongo_clients, get_x_sessions_client
from app.exceptions.handlers import register_exception_handlers
from app.exceptions.sessions import EmptySessionPoolError
from app.repositories.sessions.session_repository import XSessionRepository
from app.routes import health

# Uvicorn only configures its own loggers, so without this the application's own
# records are dropped and only warnings and above ever surface.
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [pid=%(process)d] %(levelname)s %(name)s - %(message)s",
)


@asynccontextmanager
async def lifespan(api: FastAPI) -> AsyncIterator[None]:
    # Fail fast: ping() forces a real connection at start-up, so an unreachable
    # Mongo stops the boot instead of 500-ing every request later. A single
    # await for now — this becomes an asyncio.gather when Redis joins, which is
    # the point of pinging the datastores concurrently (CLAUDE.md §3).
    mongo_client = get_x_sessions_client()
    await mongo_client.admin.command("ping")

    pool = XSessionPool(
        session_repository=XSessionRepository(
            mongo_db=mongo_client[settings.X_SESSIONS_MONGODB_DB_NAME]
        ),
        refresh_interval_seconds=settings.X_SESSIONS_POOL_REFRESH_SECONDS,
    )
    # A failure here propagates on purpose: an unreadable session store at boot
    # is not something to recover from silently. The pool logs its own size.
    await pool.load()
    if not pool.sessions:
        raise EmptySessionPoolError()

    pool.start_refreshing()

    # Only the pool goes on app.state; dependencies read it from there rather
    # than from a module global (CLAUDE.md §3). X itself is never called at
    # start-up: its outage is a per-request 502, it must not block the boot.
    api.state.x_session_pool = pool

    try:
        yield
    finally:
        await pool.stop_refreshing()
        await close_mongo_clients()


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=(
        "Read-only lookup API for X/Twitter users, posts and timelines. "
        "See docs/PROJECT.md for the endpoint blueprint."
    ),
    lifespan=lifespan,
)

register_exception_handlers(app)

app.include_router(health.router)
