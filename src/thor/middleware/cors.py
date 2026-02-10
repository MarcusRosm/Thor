"""
CORS (Cross-Origin Resource Sharing) middleware.
"""

import re as _re
from typing import Any

from thor.middleware.base import Middleware
from thor.request import Request
from thor.types import ASGIApp, Receive, Scope, Send


class CORSMiddleware(Middleware):
    """
    Cross-Origin Resource Sharing (CORS) middleware.
    Handles preflight requests and adds CORS headers.

    Security features:
      - Wildcard subdomain matching (e.g. ``*.example.com``).
      - Regex-based origin matching via ``allow_origin_regex``.
      - ``Vary: Origin`` header when the allow-list is not ``*``.
      - Blocks ``allow_credentials=True`` with a bare ``*`` origin
        (violates the CORS spec and is rejected by browsers).
    """

    def __init__(
        self,
        app: ASGIApp,
        allow_origins: list[str] | None = None,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
        allow_credentials: bool = False,
        expose_headers: list[str] | None = None,
        max_age: int = 600,
        allow_origin_regex: str | None = None,
    ) -> None:
        super().__init__(app)
        self.allow_origins = allow_origins if allow_origins is not None else ["*"]
        self.allow_methods = allow_methods or ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
        self.allow_headers = allow_headers or ["*"]
        self.allow_credentials = allow_credentials
        self.expose_headers = expose_headers or []
        self.max_age = max_age

        # Compile optional regex
        self._origin_regex: _re.Pattern[str] | None = (
            _re.compile(allow_origin_regex) if allow_origin_regex else None
        )

        # Pre-compute wildcard subdomain patterns (e.g. "*.example.com")
        self._wildcard_origins: list[str] = [
            o[1:]  # strip leading "*", keep ".example.com"
            for o in self.allow_origins
            if o.startswith("*.") and len(o) > 2
        ]

        self._allow_all = "*" in self.allow_origins and not self._wildcard_origins

        # Spec violation guard: credentials + bare wildcard
        if self.allow_credentials and self._allow_all and not self._origin_regex:
            raise ValueError(
                "allow_credentials=True cannot be used with allow_origins=['*']. "
                "Specify explicit origins or use allow_origin_regex."
            )

    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        origin = request.get_header("origin")

        if request.method == "OPTIONS":
            await self._send_preflight_response(send, origin)
            return

        async def send_with_cors(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._get_cors_headers(origin))
                message["headers"] = headers
            await send(message)

        # pyrefly: ignore [bad-argument-type]
        await self.app(scope, receive, send_with_cors)

    def _is_origin_allowed(self, origin: str) -> bool:
        """Check if *origin* is allowed by list, wildcard subdomain, or regex."""
        if self._allow_all:
            return True
        if origin in self.allow_origins:
            return True
        # Wildcard subdomain: *.example.com  matches  foo.example.com
        for suffix in self._wildcard_origins:
            if origin.endswith(suffix):
                return True
        # Regex fallback
        if self._origin_regex and self._origin_regex.fullmatch(origin):
            return True
        return False

    def _get_cors_headers(self, origin: str | None) -> list[tuple[bytes, bytes]]:
        """Generate CORS response headers."""
        headers: list[tuple[bytes, bytes]] = []

        if self._allow_all and not self.allow_credentials:
            # Bare wildcard: no Vary needed
            headers.append((b"access-control-allow-origin", b"*"))
        elif origin and self._is_origin_allowed(origin):
            # Reflect the specific origin back
            headers.append((b"access-control-allow-origin", origin.encode()))
            # Vary: Origin is required when the header is not a bare "*"
            headers.append((b"vary", b"Origin"))

        if self.allow_credentials:
            headers.append((b"access-control-allow-credentials", b"true"))

        if self.expose_headers:
            headers.append((
                b"access-control-expose-headers",
                ", ".join(self.expose_headers).encode(),
            ))

        return headers

    async def _send_preflight_response(self, send: Send, origin: str | None) -> None:
        """Send a preflight (OPTIONS) response."""
        headers = self._get_cors_headers(origin)
        headers.append((
            b"access-control-allow-methods",
            ", ".join(self.allow_methods).encode(),
        ))
        headers.append((
            b"access-control-allow-headers",
            ", ".join(self.allow_headers).encode(),
        ))
        headers.append((
            b"access-control-max-age",
            str(self.max_age).encode(),
        ))

        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": headers,
        })
        await send({
            "type": "http.response.body",
            "body": b"",
        })
