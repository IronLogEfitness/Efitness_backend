"""Application error types and the handler that turns them into JSON responses.

Services raise these HTTP-agnostic errors (e.g. ``NotFoundError``) instead of
``fastapi.HTTPException``. A single handler registered in ``create_app`` maps
them to ``{"detail": ...}`` responses, so the business layer never imports
FastAPI.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for expected, HTTP-mappable application errors."""

    status_code: int = 500
    detail: str = "Internal server error"

    def __init__(self, detail: str | None = None):
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class BadRequestError(AppError):
    status_code = 400
    detail = "Bad request"


class UnauthorizedError(AppError):
    status_code = 401
    detail = "Not authenticated"


class NotFoundError(AppError):
    status_code = 404
    detail = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    detail = "Resource already exists"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if isinstance(exc, UnauthorizedError)
            else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )
