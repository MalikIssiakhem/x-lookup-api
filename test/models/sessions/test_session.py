import pytest
from pydantic import ValidationError

from app.models.sessions.session import XSessionInDB, XSessionStatus
from test.helpers import build_session, build_session_document

# The `**document` calls below are deliberately unchecked: they feed a malformed
# document to a validated model, which is precisely what a type checker cannot
# express — and exactly what these tests assert at runtime.


def test_a_session_without_a_ct0_is_rejected() -> None:
    document = build_session_document()
    del document["ct0"]

    with pytest.raises(ValidationError):
        XSessionInDB(**document)  # type: ignore[bad-argument-type]


def test_a_session_with_an_unknown_status_is_rejected() -> None:
    document = build_session_document(status="cooldown")

    with pytest.raises(ValidationError):
        XSessionInDB(**document)  # type: ignore[bad-argument-type]


def test_a_session_repr_does_not_contain_its_credentials() -> None:
    session = build_session(auth_token="leaky-auth-token", ct0="leaky-ct0")

    # repr() is what ends up in a traceback frame, a debugger and a careless log
    # line. SecretStr is the mechanical guarantee behind "never log a cookie".
    rendered = f"{session!r} {session}"

    assert "leaky-auth-token" not in rendered
    assert "leaky-ct0" not in rendered


def test_a_session_still_exposes_its_credentials_on_purpose() -> None:
    session = build_session(auth_token="usable-auth-token")

    assert session.auth_token.get_secret_value() == "usable-auth-token"


def test_a_session_defaults_to_the_cookie_kind() -> None:
    document = build_session_document()
    del document["kind"]

    session = XSessionInDB(**document)  # type: ignore[bad-argument-type]

    assert session.kind == "cookie"
    assert session.status is XSessionStatus.ACTIVE
