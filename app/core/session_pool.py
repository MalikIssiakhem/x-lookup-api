import asyncio
import logging
from datetime import datetime, timezone

from app.models.sessions.session import XSessionInDB
from app.repositories.sessions.session_repository import XSessionRepository

logger = logging.getLogger(__name__)


class XSessionPool:
    """The usable X sessions, held in memory and refreshed in the background.

    Lives in core/ because it belongs to no layer: it is loaded by the lifespan
    and will be read by the X client. The whole point is that the hot path never
    pays a database round-trip to pick an account (CLAUDE.md §3).

    This ticket loads, holds and refreshes. Choosing a session for a given
    endpoint — and the rate-limit accounting that decides which ones are still
    eligible — arrives with the client that reads X's response headers.
    """

    def __init__(
        self,
        session_repository: XSessionRepository,
        refresh_interval_seconds: float,
    ) -> None:
        self._session_repository = session_repository
        self._refresh_interval_seconds = refresh_interval_seconds
        self._sessions: tuple[XSessionInDB, ...] = ()
        self._refresh_task: asyncio.Task[None] | None = None
        self._last_successful_refresh: datetime | None = None
        self._consecutive_refresh_failures = 0

    @property
    def sessions(self) -> tuple[XSessionInDB, ...]:
        """The current snapshot.

        A tuple, and replaced wholesale rather than mutated: a reader that grabs
        it keeps a consistent view even if a refresh lands mid-iteration.
        """
        return self._sessions

    @property
    def staleness_seconds(self) -> float | None:
        """How old the snapshot is, or None if nothing was ever loaded.

        Keeping the previous snapshot when a refresh fails is the right call,
        but without this it has no time bound: Mongo can be down for six hours
        while the pool serves accounts that were evicted five hours ago, and
        nothing says so. Measured here, reported in the failure logs.

        Deliberately not exposed on /health: that route is the one exempted from
        the RapidAPI secret, so anything it returns is public, and "this API's
        session store has been down for six hours" is exactly the operational
        detail CLAUDE.md §5 keeps off it. It belongs on an authenticated ops
        endpoint.
        """
        if self._last_successful_refresh is None:
            return None
        return (
            datetime.now(timezone.utc) - self._last_successful_refresh
        ).total_seconds()

    async def load(self) -> None:
        """Rebuild the snapshot from Mongo.

        The new tuple is built first and only then rebound. There is a single
        event loop and the rebind is atomic, so no reader ever observes a
        half-built pool — which is why none of this needs a lock.
        """
        previous_count = len(self._sessions)
        self._sessions = tuple(await self._session_repository.list_usable_sessions())
        self._last_successful_refresh = datetime.now(timezone.utc)
        self._consecutive_refresh_failures = 0
        self._log_size(previous_count)

    def start_refreshing(self) -> None:
        # Idempotent: a second create_task would orphan the first, which would
        # keep refreshing forever with nobody holding a reference to cancel it.
        if self._refresh_task is not None:
            return
        self._refresh_task = asyncio.create_task(self._refresh_forever())

    async def stop_refreshing(self) -> None:
        task = self._refresh_task
        if task is None:
            return
        self._refresh_task = None
        task.cancel()
        # Awaiting the cancellation is what makes shutdown deterministic: without
        # it the loop can be torn down while the task is still inside a Mongo
        # call, which surfaces as noise on every single shutdown.
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _refresh_forever(self) -> None:
        while True:
            # The sleep sits outside the try to keep the waiting plainly apart
            # from the work. Not for cancellation: asyncio.CancelledError derives
            # from BaseException since Python 3.8, so it crosses `except
            # Exception` from either side of this line.
            await asyncio.sleep(self._refresh_interval_seconds)
            try:
                await self.load()
            except Exception as e:  # noqa: BLE001 - see below
                # Deliberately broad, and deliberately not re-raised: a Mongo
                # blip must not kill the refresh task nor empty the pool. The
                # previous snapshot stays in place and the API keeps serving on
                # the accounts it already had. Narrowing this to the repository's
                # own errors would let an unexpected one silently stop every
                # future refresh, which is the failure nobody notices.
                self._consecutive_refresh_failures += 1
                self._log_refresh_failure(e)

    def _log_size(self, previous_count: int) -> None:
        count = len(self._sessions)
        if count == 0:
            # A *successful* read returning nothing is not a Mongo blip: every
            # account is evicted or cooling down, or a status value was renamed.
            # Emptying the pool is the correct outcome — serving from a stale
            # snapshot would mean hammering X with dead tokens — but doing it
            # silently is not.
            logger.error(
                "The X session pool is empty after a successful read: every "
                "account is evicted, cooling down, or no longer matches the model"
            )
        elif count != previous_count:
            logger.info(
                f"The X session pool now holds {count} usable session(s) "
                f"(was {previous_count})"
            )

    def _log_refresh_failure(self, error: Exception) -> None:
        staleness = self.staleness_seconds
        age = f"{staleness:.0f}s ago" if staleness is not None else "never"
        message = (
            f"Failed to refresh the X session pool "
            f"(attempt {self._consecutive_refresh_failures}, "
            f"last success {age}) - {error}"
        )
        # The age is in the message rather than the attempt count alone: three
        # attempts mean nothing without the interval, whereas "last success 612s
        # ago" is actionable in a log line, with no endpoint to read it from.
        # A single failure is a blip; from the second on, the snapshot is
        # measurably stale and the stack trace is worth having.
        if self._consecutive_refresh_failures == 1:
            logger.warning(message)
        else:
            logger.exception(message)
