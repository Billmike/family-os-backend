from typing import Any

from fastapi import HTTPException, status


class AppError(HTTPException):
    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail={"detail": detail, "code": code}, headers=headers)


def unauthorized(detail: str = "Not authenticated", code: str = "unauthorized") -> AppError:
    return AppError(status.HTTP_401_UNAUTHORIZED, detail, code, headers={"WWW-Authenticate": "Bearer"})


def forbidden(detail: str = "Forbidden", code: str = "forbidden") -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, detail, code)


def not_found(detail: str = "Not found", code: str = "not_found") -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, detail, code)


def conflict(detail: str = "Conflict", code: str = "conflict") -> AppError:
    return AppError(status.HTTP_409_CONFLICT, detail, code)


def bad_request(detail: str = "Bad request", code: str = "bad_request") -> AppError:
    return AppError(status.HTTP_400_BAD_REQUEST, detail, code)


def error_body(exc: HTTPException) -> dict[str, Any]:
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return exc.detail
    return {"detail": str(exc.detail), "code": "error"}
