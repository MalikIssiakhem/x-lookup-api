import pytest

from app.config import Settings


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

    assert Settings().LOG_LEVEL == "INFO"


def test_settings_read_the_log_level_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    assert Settings().LOG_LEVEL == "DEBUG"
