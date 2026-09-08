import logging

from fastapi import FastAPI

from app.config import settings
from app.exceptions.handlers import register_exception_handlers
from app.routes import health

# Uvicorn only configures its own loggers, so without this the application's own
# records are dropped and only warnings and above ever surface.
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [pid=%(process)d] %(levelname)s %(name)s - %(message)s",
)

# No lifespan yet: it arrives with the datastores and the session pool, whose
# start-up pings are its whole reason to exist (CLAUDE.md §3). An empty
# asynccontextmanager here would be plumbing without a consumer.
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=(
        "Read-only lookup API for X/Twitter users, posts and timelines. "
        "See docs/PROJECT.md for the endpoint blueprint."
    ),
)

register_exception_handlers(app)

app.include_router(health.router)
