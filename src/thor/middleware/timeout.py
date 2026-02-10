"""
Request timeout middleware.
"""

import asyncio
import logging

from thor.middleware.base import Middleware
from thor.types import ASGIApp, Receive, Scope, Send


class TimeoutMiddleware(Middleware):
    """
    Per-request timeout enforcement.

    Wraps each request handler invocation with ``asyncio.wait_for``.
    If the handler does not complete within the configured timeout,
    a 504 Gateway Timeout response is returned to the client and
    the handler task is cancelled.

    Usage:
        app.add_middleware(TimeoutMiddleware, timeout=15.0)
    """

    def __init__(
        self,
        app: ASGIApp,
        timeout: float = 15.0,
    ) -> None:
        super().__init__(app)
        self._timeout = timeout
        self._logger = logging.getLogger("thor.timeout")

    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        from thor.exceptions import RequestTimeout

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            request_id = scope.get("request_id", "-")
            path = scope.get("path", "-")
            self._logger.warning(
                "Request timed out after %.1fs  path=%s request_id=%s",
                self._timeout,
                path,
                request_id,
            )
            raise RequestTimeout(
                f"Request exceeded {self._timeout}s time limit"
            )
