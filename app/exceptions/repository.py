class RepositoryError(Exception):
    """Base class for repository-layer errors.

    Carries an operator-facing `message` plus optional `operation`/`detail` for
    the logs. No HTTP handler is registered for it yet: nothing serves a request
    off Mongo until the first lookup route (ticket 4), and a handler with no
    request path to fire on would be untested plumbing.
    """

    def __init__(
        self, message: str, operation: str | None = None, detail: str | None = None
    ) -> None:
        self.message = message
        self.operation = operation
        self.detail = detail

        full_message = message
        if operation:
            full_message += f" | operation={operation}"
        if detail:
            full_message += f" | detail={detail}"

        super().__init__(full_message)


class RepositoryDatabaseOperationError(RepositoryError):
    """Raised when a MongoDB operation fails (unreachable, timeout, write error…)."""


class RepositoryDataCorruptionError(RepositoryError):
    """Raised when a document exists but does not match its Pydantic model."""
