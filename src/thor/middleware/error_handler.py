"""
Error handling middleware.
"""

import logging
import uuid
from typing import Any

from thor.middleware.base import Middleware
from thor.types import ASGIApp, Receive, Scope, Send


class ErrorHandlerMiddleware(Middleware):
    """
    Global error handling middleware.
    Catches exceptions and returns appropriate error responses.
    
    Always logs the full exception server-side. Never exposes internal
    details to the client. Attaches a unique request ID to every
    response for traceability.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        debug: bool = False,
    ) -> None:
        super().__init__(app)
        self.debug = debug
        self._logger = logging.getLogger("thor.errors")
    
    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        from thor.exceptions import HTTPException
        from thor.response import JSONResponse
        
        request_id = str(uuid.uuid4())
        scope["request_id"] = request_id
        
        # Inject X-Request-ID header into every response
        async def send_with_request_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)
        
        try:
            # pyrefly: ignore [bad-argument-type]
            await self.app(scope, receive, send_with_request_id)
        except HTTPException as exc:
            # Log client errors at warning, server errors at error
            if exc.status_code >= 500:
                self._logger.error(
                    "request_id=%s status=%d detail=%s",
                    request_id, exc.status_code, exc.detail,
                    exc_info=True,
                )
            else:
                self._logger.warning(
                    "request_id=%s status=%d detail=%s",
                    request_id, exc.status_code, exc.detail,
                )
            response = JSONResponse(
                content={
                    "error": exc.detail,
                    "status_code": exc.status_code,
                    "request_id": request_id,
                },
                status_code=exc.status_code,
                headers=exc.headers,
            )
            # pyrefly: ignore [bad-argument-type]
            await response(send_with_request_id)
        except Exception as exc:
            # Always log full traceback server-side
            self._logger.exception(
                "Unhandled exception request_id=%s: %s",
                request_id, exc,
            )
            # Never expose internal details to the client
            response = JSONResponse(
                content={
                    "error": "Internal Server Error",
                    "status_code": 500,
                    "request_id": request_id,
                },
                status_code=500,
            )
            # pyrefly: ignore [bad-argument-type]
            await response(send_with_request_id)
