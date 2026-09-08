import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

# Starlette's HTTPException, not FastAPI's subclass: the router raises the base
# class for a 404 on an unknown path and a 405 on a wrong method, and a handler
# registered on the subclass never matches those. Registering on the base covers
# both, since fastapi.HTTPException inherits from it.
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

# Every response this API produces on an error path uses the same envelope:
# {"error": "<machine-readable code>", "message": "<human-readable text>"}.
# RapidAPI clients have no access to the code, so `error` is the only stable
# thing they can branch on — it is part of the contract we sell (CLAUDE.md §4).


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Rewrite FastAPI's own HTTP errors into the shared envelope.

    Without this, a request to an unknown path answers `{"detail": "Not Found"}`
    while our own errors answer `{"error", "message"}` — two shapes for the same
    API. Not logged: a 404 on a path that does not exist is an expected answer,
    not a failure of ours.
    """
    status_code = getattr(exc, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR)
    detail = getattr(exc, "detail", None)
    return JSONResponse(
        status_code=status_code,
        content={
            "error": _ERROR_CODES.get(status_code, "http_error"),
            "message": str(detail) if detail else "The request could not be served.",
        },
        headers=getattr(exc, "headers", None),
    )


async def unhandled_exception_handler(
    _request: Request, exc: Exception
) -> JSONResponse:
    """Last-resort handler: anything that reached here is a bug on our side.

    Logged once, here, with its stack trace — this is the place the failure
    surfaces (CLAUDE.md §4). The client gets a generic message: the cause can
    carry a Mongo URI, a session cookie or an internal path, and none of that
    belongs in a response body.
    """
    logger.exception(f"Unhandled error - {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred.",
        },
    )


# Only the codes FastAPI itself can raise before any of our code runs. Business
# error codes (user_not_found, upstream_error…) are not listed here: they come
# from custom exceptions with their own handlers, added with the routes that
# raise them.
_ERROR_CODES = {
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
}


def register_exception_handlers(app: FastAPI) -> None:
    # Order matters only in that the catch-all on Exception must be registered
    # last: it is the widest net and would otherwise swallow the specific ones.
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
