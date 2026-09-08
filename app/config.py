from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Source of truth for the configuration (CLAUDE.md §5).

    Only holds what the code actually reads today. The datastore URLs, the
    RapidAPI proxy secret and the cache TTLs arrive with the tickets that
    consume them: front-loading them would put variables in .env.example that
    nothing reads, and make the boot fail-fast on settings nobody uses.

    Required values carry no default on purpose — a missing one must stop the
    boot. Only genuinely optional knobs get one, as below.
    """

    # Operational knobs, all optional: the app boots with these defaults and
    # they change nothing about correctness.
    LOG_LEVEL: str = "INFO"
    API_TITLE: str = "X Lookup API"
    API_VERSION: str = "0.1.0"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
