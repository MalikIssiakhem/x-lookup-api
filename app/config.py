from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Source of truth for the configuration (CLAUDE.md §5).

    Only holds what the code actually reads today. The Redis URL and the cache
    TTLs arrive with the cache that consumes them; the RapidAPI proxy secret
    with its middleware. Front-loading them would put variables in .env.example
    that nothing reads, and fail the boot on settings nobody uses.
    """

    # X account sessions — Mongo is the source of truth for the pool (accounts,
    # cookies, state, dates). Names are spelled out rather than a generic
    # MONGODB_URL: a second datastore is coming, and a generic name would not
    # survive it (CLAUDE.md §4).
    #
    # No defaults on purpose: a missing value must stop the boot, never fall
    # back to some other database. Percent-encode the special characters of the
    # password in the URI (& -> %26, ! -> %21, % -> %25).
    X_SESSIONS_MONGODB_URL: str
    X_SESSIONS_MONGODB_DB_NAME: str
    X_SESSIONS_COLLECTION: str = "sessions"

    # How often the in-memory pool is rebuilt from Mongo in the background. The
    # hot path never reads Mongo, so this is the only thing that picks up an
    # account added, evicted or cooled down by another process.
    X_SESSIONS_POOL_REFRESH_SECONDS: float = 300.0

    # Operational knobs, all optional: the app boots with these defaults and
    # they change nothing about correctness.
    LOG_LEVEL: str = "INFO"
    API_TITLE: str = "X Lookup API"
    API_VERSION: str = "0.1.0"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()  # type: ignore[call-arg]
