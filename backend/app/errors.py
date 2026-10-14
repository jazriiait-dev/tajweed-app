"""Errors the API reports to clients.

Every error has a stable `code`. Apps translate the code into Arabic, English
or French; the English `message` is only a fallback for developers.
"""

from __future__ import annotations


class AppError(Exception):
    status = 400

    def __init__(self, code: str, message: str, *, status: int | None = None,
                 commit: bool = False, details: object = None):
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status
        # When true, changes made before the error are kept (for example the
        # failed sign-in counter) instead of being rolled back.
        self.commit = commit
        self.details = details

    def to_dict(self) -> dict:
        body: dict = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return {"error": body}


class NotSignedIn(AppError):
    status = 401

    def __init__(self, code: str = "not_signed_in", message: str = "Sign in to continue.", **kw):
        super().__init__(code, message, **kw)


class Forbidden(AppError):
    status = 403

    def __init__(self, code: str = "not_allowed", message: str = "You are not allowed to do this.", **kw):
        super().__init__(code, message, **kw)


class NotFound(AppError):
    status = 404

    def __init__(self, code: str = "not_found", message: str = "Not found.", **kw):
        super().__init__(code, message, **kw)


class Conflict(AppError):
    status = 409
