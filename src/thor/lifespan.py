"""
Lifespan management for Thor framework.
Handles application startup and shutdown events.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from thor.types import ASGIApp, LifespanHandler, Receive, Scope, Send, State


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("thor.lifespan")


@dataclass
class LifespanState:
    """
    Application state that persists across the application lifespan.
    Used for database connections, caches, and other shared resources.
    """
    
    _data: dict[str, Any] = field(default_factory=dict)
    
    def __getitem__(self, key: str) -> Any:
        return self._data[key]
    
    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
    
    def __delitem__(self, key: str) -> None:
        del self._data[key]
    
    def __contains__(self, key: object) -> bool:
        return key in self._data
    
    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
    
    def clear(self) -> None:
        self._data.clear()


class Lifespan:
    """
    Lifespan manager for handling startup and shutdown events.
    
    Follows the Template Method pattern - defines the skeleton
    of the lifespan algorithm while allowing customization.
    
    Usage:
        lifespan = Lifespan()
        
        @lifespan.on_startup
        async def startup():
            # Initialize resources
            pass
        
        @lifespan.on_shutdown
        async def shutdown():
            # Cleanup resources
            pass
    """
    
    def __init__(self) -> None:
        self._startup_handlers: list[LifespanHandler] = []
        self._shutdown_handlers: list[LifespanHandler] = []
        self._context_manager: Callable[[LifespanState], AsyncGenerator[None, None]] | None = None
        self.state = LifespanState()
    
    def on_startup(self, handler: LifespanHandler) -> LifespanHandler:
        """Decorator to register a startup handler."""
        self._startup_handlers.append(handler)
        return handler
    
    def on_shutdown(self, handler: LifespanHandler) -> LifespanHandler:
        """Decorator to register a shutdown handler."""
        self._shutdown_handlers.append(handler)
        return handler
    
    def context(
        self,
        cm: Callable[[LifespanState], AsyncGenerator[None, None]],
    ) -> Callable[[LifespanState], AsyncGenerator[None, None]]:
        """
        Decorator to set a lifespan context manager.
        
        Usage:
            @lifespan.context
            async def lifespan_context(state):
                # Startup code
                state["db"] = await create_database_pool()
                yield
                # Shutdown code
                await state["db"].close()
        """
        self._context_manager = cm
        return cm
    
    async def startup(self) -> None:
        """Run all startup handlers."""
        for handler in self._startup_handlers:
            await handler()
    
    async def shutdown(self) -> None:
        """Run all shutdown handlers in reverse order."""
        for handler in reversed(self._shutdown_handlers):
            await handler()
    
    @asynccontextmanager
    async def __call__(self, state: LifespanState) -> AsyncGenerator[None, None]:
        """Execute the lifespan context."""
        if self._context_manager:
            # pyrefly: ignore [bad-context-manager]
            async with self._context_manager(state):
                yield
        else:
            await self.startup()
            try:
                yield
            finally:
                await self.shutdown()


class LifespanProtocolHandler:
    """
    ASGI lifespan protocol handler.
    Manages the application lifecycle events.

    Tracks in-flight HTTP requests and drains them gracefully
    on shutdown before running cleanup handlers.
    """

    # Maximum seconds to wait for in-flight requests to finish
    DEFAULT_SHUTDOWN_TIMEOUT: float = 30.0

    def __init__(
        self,
        app: ASGIApp,
        lifespan: Lifespan | None = None,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        self._app = app
        self._lifespan = lifespan or Lifespan()
        self.state = self._lifespan.state
        self._shutdown_timeout = shutdown_timeout
        self._inflight: int = 0
        self._inflight_zero = asyncio.Event()
        self._inflight_zero.set()  # starts at 0 → already "zero"
        self._shutting_down: bool = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle ASGI messages."""
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
        else:
            # Add state to scope for request handlers
            scope["state"] = self.state

            # Track in-flight requests
            self._inflight += 1
            self._inflight_zero.clear()
            try:
                await self._app(scope, receive, send)
            finally:
                self._inflight -= 1
                if self._inflight == 0:
                    self._inflight_zero.set()

    # ------------------------------------------------------------------
    # Lifespan protocol
    # ------------------------------------------------------------------

    async def _handle_lifespan(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Handle lifespan events."""
        async with self._lifespan(self.state):
            while True:
                message = await receive()

                if message["type"] == "lifespan.startup":
                    try:
                        await send({"type": "lifespan.startup.complete"})
                    except Exception as exc:
                        await send({
                            "type": "lifespan.startup.failed",
                            "message": str(exc),
                        })
                        raise

                elif message["type"] == "lifespan.shutdown":
                    self._shutting_down = True
                    await self._drain_requests()
                    try:
                        await send({"type": "lifespan.shutdown.complete"})
                    except Exception as exc:
                        await send({
                            "type": "lifespan.shutdown.failed",
                            "message": str(exc),
                        })
                        raise
                    return

    async def _drain_requests(self) -> None:
        """Wait for in-flight requests to finish, with a timeout."""
        if self._inflight == 0:
            return

        logger.info(
            "Waiting for %d in-flight request(s) to finish (timeout=%ds)...",
            self._inflight,
            self._shutdown_timeout,
        )
        try:
            await asyncio.wait_for(
                self._inflight_zero.wait(),
                timeout=self._shutdown_timeout,
            )
            logger.info("All in-flight requests completed.")
        except asyncio.TimeoutError:
            logger.warning(
                "Shutdown timeout reached with %d request(s) still in-flight. "
                "Proceeding with shutdown.",
                self._inflight,
            )

    @property
    def is_shutting_down(self) -> bool:
        """Check whether the application is in the process of shutting down."""
        return self._shutting_down

    @property
    def inflight_requests(self) -> int:
        """Number of currently in-flight HTTP requests."""
        return self._inflight


def lifespan_context(
    startup: LifespanHandler | None = None,
    shutdown: LifespanHandler | None = None,
) -> Callable[[LifespanState], AsyncGenerator[None, None]]:
    """
    Create a lifespan context manager from startup and shutdown handlers.
    
    Usage:
        @lifespan_context(startup=init_db, shutdown=close_db)
        async def my_lifespan(state):
            yield
    """
    @asynccontextmanager
    async def context(state: LifespanState) -> AsyncGenerator[None, None]:
        if startup:
            await startup()
        try:
            yield
        finally:
            if shutdown:
                await shutdown()
    
    # pyrefly: ignore [bad-return]
    return context
