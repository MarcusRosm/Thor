"""
CSRF (Cross-Site Request Forgery) protection middleware.
"""

import hmac
import secrets
from typing import Any

from thor.cookies import CookieOptions, format_set_cookie
from thor.middleware.base import Middleware
from thor.request import Request
from thor.types import ASGIApp, Receive, Scope, Send

# HTTP methods that are considered "safe" (read-only) and exempt from CSRF checks
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Default cookie / header / form field names
DEFAULT_COOKIE_NAME: str = "thor_csrf"
DEFAULT_HEADER_NAME: str = "x-csrf-token"
DEFAULT_FORM_FIELD: str = "_csrf_token"
DEFAULT_TOKEN_LENGTH: int = 32


class CSRFMiddleware(Middleware):
    """
    CSRF protection middleware.

    For every request, ensures a CSRF token cookie is set.  For
    state-mutating methods (POST, PUT, PATCH, DELETE) the middleware
    verifies the token submitted via header or form field matches
    the cookie value using constant-time comparison.

    Usage:
        app.add_middleware(
            CSRFMiddleware,
            secret_key="your-secret-key",
        )

    Clients must:
        1. Read the CSRF cookie value (JavaScript-readable by default).
        2. Submit it back as the ``X-CSRF-Token`` header or as the
           ``_csrf_token`` form field on every mutating request.
    """

    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        cookie_name: str = DEFAULT_COOKIE_NAME,
        header_name: str = DEFAULT_HEADER_NAME,
        form_field: str = DEFAULT_FORM_FIELD,
        token_length: int = DEFAULT_TOKEN_LENGTH,
        safe_methods: frozenset[str] = SAFE_METHODS,
        exclude_paths: list[str] | None = None,
        cookie_options: CookieOptions | None = None,
    ) -> None:
        super().__init__(app)
        self._secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key
        self._cookie_name = cookie_name
        self._header_name = header_name
        self._form_field = form_field
        self._token_length = token_length
        self._safe_methods = safe_methods
        self._exclude_paths = exclude_paths or []
        # CSRF cookie must be readable by JS; httponly=False by design
        self._cookie_options = cookie_options or CookieOptions(
            httponly=False,
            samesite="lax",
            secure=True,
            path="/",
        )

    def generate_token(self) -> str:
        """Generate a new random CSRF token."""
        return secrets.token_urlsafe(self._token_length)

    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        from thor.exceptions import Forbidden
        from thor.response import JSONResponse

        request = Request(scope, receive)

        # Skip excluded paths
        if any(request.path.startswith(p) for p in self._exclude_paths):
            await self.app(scope, receive, send)
            return

        # Retrieve or generate token
        cookie_token = request.get_cookie(self._cookie_name)

        if not cookie_token:
            cookie_token = self.generate_token()

        # Expose current CSRF token on scope so handlers can read it
        scope["csrf_token"] = cookie_token

        # Validate on unsafe methods
        if request.method not in self._safe_methods:
            submitted_token = request.get_header(self._header_name)
            if not submitted_token:
                submitted_token = await self._get_form_token(request)

            if not submitted_token or not self._tokens_match(
                cookie_token, submitted_token
            ):
                response = JSONResponse(
                    content={
                        "error": "CSRF token missing or invalid",
                        "status_code": 403,
                    },
                    status_code=403,
                )
                await response(send)
                return

        # Wrap send to ensure CSRF cookie is always set / refreshed
        async def send_with_csrf(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                cookie_value = format_set_cookie(
                    self._cookie_name,
                    # pyrefly: ignore [bad-argument-type]
                    cookie_token,
                    self._cookie_options,
                )
                headers.append((b"set-cookie", cookie_value.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        # pyrefly: ignore [bad-argument-type]
        await self.app(scope, receive, send_with_csrf)

    @staticmethod
    def _tokens_match(expected: str, submitted: str) -> bool:
        """Constant-time comparison to prevent timing attacks."""
        return hmac.compare_digest(expected.encode(), submitted.encode())

    @staticmethod
    async def _get_form_token(request: Request) -> str | None:
        """Try to extract CSRF token from form body."""
        if "application/x-www-form-urlencoded" in request.content_type:
            form = await request.form()
            value = form.get(DEFAULT_FORM_FIELD)
            if isinstance(value, list):
                return value[0] if value else None
            return value
        return None
