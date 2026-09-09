class EmptySessionPoolError(Exception):
    """Raised at start-up when Mongo holds no usable session.

    Stops the boot rather than letting the API come up and answer every single
    lookup with a 502 (CLAUDE.md §3). An API with an empty pool is not degraded,
    it is incapable — and a container that refuses to start is far easier to
    notice than one that is up and failing.
    """

    def __init__(self) -> None:
        self.message = (
            "No usable X session in the pool: every account is evicted, cooling "
            "down, or the collection is empty. Refusing to start."
        )
        super().__init__(self.message)
