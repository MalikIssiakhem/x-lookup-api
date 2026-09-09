import pytest

from app.config import Settings

# The `type: ignore` on each construction is the same one app/config.py carries:
# the required datastore settings have no default, so a bare Settings() looks
# like a missing argument to the type checker while pydantic reads it from the
# environment at runtime. That gap is the fail-fast working as intended.


@pytest.fixture(autouse=True)
def ignore_the_local_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detach Settings from .env for the whole module.

    Without this, a developer with a populated .env would get different results
    from CI. `_env_file=None` at the call site would do the same, but it is an
    undeclared keyword on the generated __init__ and the type checker rejects it.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)


def test_settings_fall_back_to_info_when_the_log_level_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    assert Settings().LOG_LEVEL == "INFO"  # type: ignore[missing-argument]


def test_settings_read_the_log_level_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    assert Settings().LOG_LEVEL == "DEBUG"  # type: ignore[missing-argument]


def test_the_session_pool_refresh_interval_has_a_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("X_SESSIONS_POOL_REFRESH_SECONDS", raising=False)

    assert Settings().X_SESSIONS_POOL_REFRESH_SECONDS == 300.0  # type: ignore[missing-argument]


def test_a_missing_session_store_url_stops_the_settings_from_building(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("X_SESSIONS_MONGODB_URL", raising=False)

    # No default on purpose: the boot must stop rather than silently point at
    # some other database (CLAUDE.md §5).
    with pytest.raises(ValueError):
        Settings()  # type: ignore[missing-argument]
