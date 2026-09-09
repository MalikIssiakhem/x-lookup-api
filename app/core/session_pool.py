import asyncio
import logging

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

    @property
    def sessions(self) -> tuple[XSessionInDB, ...]:
        """The current snapshot.

        A tuple, and replaced wholesale rather than mutated: a reader that grabs
        it keeps a consistent view even if a refresh lands mid-iteration.
        """
        return self._sessions

    async def load(self) -> None:
        """Rebuild the snapshot from Mongo.

        The new tuple is built first and only then rebound. There is a single
        event loop and the rebind is atomic, so no reader ever observes a
        half-built pool — which is why none of this needs a lock.
        """
        self._sessions = tuple(await self._session_repository.list_usable_sessions())

    def start_refreshing(self) -> None:
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
            # The sleep sits outside the try so that cancellation propagates
            # instead of being swallowed as "a failed refresh".
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
                logger.exception(f"Failed to refresh the X session pool - {e}")
