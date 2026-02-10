"""
Request logging middleware.
"""

import logging
import time
from typing import Any

from thor.middleware.base import Middleware
from thor.request import Request
from thor.types import ASGIApp, Receive, Scope, Send


class RequestLoggingMiddleware(Middleware):
    """
    Request logging middleware.
    Logs incoming requests and response status codes using
    Python's standard logging module.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        logger: Any = None,
        log_level: int | None = None,
    ) -> None:
        super().__init__(app)
        self._logger = logger or logging.getLogger("thor.access")
        self._log_level = log_level or logging.INFO
    
    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        start_time = time.perf_counter()
        request_id = scope.get("request_id", "-")
        
        status_code = 0
        
        async def capture_send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)
        
        try:
            # pyrefly: ignore [bad-argument-type]
            await self.app(scope, receive, capture_send)
        finally:
            duration = (time.perf_counter() - start_time) * 1000
            self._logger.log(
                self._log_level,
                "%s %s %d %.2fms request_id=%s client=%s",
                request.method,
                request.path,
                status_code,
                duration,
                request_id,
                request.client[0] if request.client else "-",
            )
