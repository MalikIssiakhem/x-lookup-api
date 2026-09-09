from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, SecretStr


class XSessionStatus(StrEnum):
    """Lifecycle of an account in the pool.

    Deliberately two states and not three: a cooldown is expressed by
    `cooldown_until` alone, never by a status. With a third COOLDOWN state,
    something would have to flip the account back to ACTIVE when the cooldown
    expires — and whatever forgets to do it strands a perfectly good account
    outside the pool forever. A timestamp needs nobody to reset it.
    """

    ACTIVE = "active"
    # Token expired, invalid or account locked (X error 89 / 239 / 326). Never
    # comes back on its own: the credentials have to be re-minted.
    EVICTED = "evicted"


class XSessionInDB(BaseModel):
    """One usable X account session, as the pool holds it.

    This carries only what a lookup needs. The account password, its recovery
    mailbox and its TOTP secret live in the same Mongo document but are never
    loaded (see XSessionRepository): they belong to the tool that re-mints
    sessions, not to a read-only lookup API. What is never loaded cannot leak.

    Never exposed by a route — it is an internal model, not an API contract.
    """

    username: str
    # Single-valued today because every account we source is a cookie pair. The
    # field exists so adding an OAuth1 variant later is a discriminated union
    # rather than a rewrite of everything that reads a session.
    kind: Literal["cookie"] = "cookie"
    # SecretStr renders as '**********' in every repr, str and traceback, so a
    # stray log line or a stack trace cannot spill a live session (CLAUDE.md §4).
    auth_token: SecretStr
    ct0: SecretStr
    status: XSessionStatus
    cooldown_until: datetime | None = None
