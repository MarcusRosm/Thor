"""
Thor framework exceptions.
Following the Single Responsibility Principle - each exception handles one type of error.
"""

from typing import Any


class ThorException(Exception):
    """Base exception for all Thor framework errors."""
    
    def __init__(self, message: str = "An error occurred") -> None:
        self.message = message
        super().__init__(self.message)


class HTTPException(ThorException):
    """HTTP-related exceptions with status codes."""
    
    def __init__(
        self,
        status_code: int = 500,
        detail: str = "Internal Server Error",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.headers = headers or {}
        super().__init__(detail)


class BadRequest(HTTPException):
    """400 Bad Request."""
    
    def __init__(self, detail: str = "Bad Request") -> None:
        super().__init__(400, detail)


class Unauthorized(HTTPException):
    """401 Unauthorized."""
    
    def __init__(
        self,
        detail: str = "Unauthorized",
        headers: dict[str, str] | None = None,
    ) -> None:
        default_headers = {"WWW-Authenticate": "Bearer"}
        if headers:
            default_headers.update(headers)
        super().__init__(401, detail, default_headers)


class Forbidden(HTTPException):
    """403 Forbidden."""
    
    def __init__(self, detail: str = "Forbidden") -> None:
        super().__init__(403, detail)


class NotFound(HTTPException):
    """404 Not Found."""
    
    def __init__(self, detail: str = "Not Found") -> None:
        super().__init__(404, detail)


class MethodNotAllowed(HTTPException):
    """405 Method Not Allowed."""
    
    def __init__(self, detail: str = "Method Not Allowed") -> None:
        super().__init__(405, detail)


class PayloadTooLarge(HTTPException):
    """413 Payload Too Large."""
    
    def __init__(self, detail: str = "Payload Too Large") -> None:
        super().__init__(413, detail)


class InternalServerError(HTTPException):
    """500 Internal Server Error."""
    
    def __init__(self, detail: str = "Internal Server Error") -> None:
        super().__init__(500, detail)


class TooManyRequests(HTTPException):
    """429 Too Many Requests — rate limit exceeded."""

    def __init__(
        self,
        detail: str = "Too Many Requests",
        retry_after: int | None = None,
    ) -> None:
        headers: dict[str, str] = {}
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        super().__init__(429, detail, headers)


class RequestTimeout(HTTPException):
    """504 Gateway Timeout — request handler exceeded time limit."""
    
    def __init__(self, detail: str = "Request Timeout") -> None:
        super().__init__(504, detail)


class SessionError(ThorException):
    """Session-related errors."""
    pass


class CookieError(ThorException):
    """Cookie-related errors."""
    pass


class AuthenticationError(ThorException):
    """Authentication-related errors."""
    pass


class RoutingError(ThorException):
    """Routing-related errors."""
    pass
