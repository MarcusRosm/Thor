"""
Rate limiting middleware.
"""

import logging
import time
from typing import Any

from thor.middleware.base import Middleware
from thor.types import ASGIApp, Receive, Scope, Send


class RateLimitMiddleware(Middleware):
    """
    Per-client rate limiting using a sliding window counter.

    Tracks request counts per client IP address in memory.
    Returns 429 Too Many Requests when the limit is exceeded.

    Usage:
        app.add_middleware(
            RateLimitMiddleware,
            max_requests=100,   # requests per window
            window_seconds=60,  # window duration
        )
    """

    def __init__(
        self,
        app: ASGIApp,
        max_requests: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._max_requests = max_requests
        self._window = window_seconds
        # client_ip -> list of request timestamps
        self._requests: dict[str, list[float]] = {}
        self._logger = logging.getLogger("thor.ratelimit")

    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        from thor.exceptions import TooManyRequests
        from thor.response import JSONResponse

        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        now = time.monotonic()

        # Prune old timestamps outside the window
        window_start = now - self._window
        timestamps = self._requests.get(client_ip, [])
        timestamps = [t for t in timestamps if t > window_start]

        if len(timestamps) >= self._max_requests:
            retry_after = int(self._window - (now - timestamps[0])) + 1
            self._logger.warning(
                "Rate limit exceeded for %s (%d/%d in %ds)",
                client_ip,
                len(timestamps),
                self._max_requests,
                self._window,
            )
            response = JSONResponse(
                content={
                    "error": "Too Many Requests",
                    "status_code": 429,
                    "retry_after": retry_after,
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(send)
            return

        timestamps.append(now)
        self._requests[client_ip] = timestamps

        # Inject rate limit info headers
        remaining = self._max_requests - len(timestamps)

        async def send_with_ratelimit(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", str(self._max_requests).encode()))
                headers.append((b"x-ratelimit-remaining", str(remaining).encode()))
                headers.append((b"x-ratelimit-reset", str(int(self._window)).encode()))
                message["headers"] = headers
            await send(message)

        # pyrefly: ignore [bad-argument-type]
        await self.app(scope, receive, send_with_ratelimit)
