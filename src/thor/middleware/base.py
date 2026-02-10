"""
Base middleware classes for Thor framework.
Implements the Chain of Responsibility pattern.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from thor.types import ASGIApp, Receive, Scope, Send


class Middleware(ABC):
    """
    Abstract base middleware class.
    
    Follows the Chain of Responsibility pattern - each middleware
    can process the request and optionally pass it to the next handler.
    
    Also follows Open/Closed Principle - new middleware can be added
    by extending this class without modifying existing code.
    """
    
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI interface - called by the server."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        await self.process(scope, receive, send)
    
    @abstractmethod
    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process the request. Must be implemented by subclasses."""
        ...


class MiddlewareStack:
    """
    Manages a stack of middleware.
    Implements the Composite pattern for middleware organization.
    """
    
    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._middleware: list[type[Middleware] | Callable[[ASGIApp], ASGIApp]] = []
        self._middleware_options: list[dict[str, Any]] = []
    
    def add(
        self,
        middleware_class: type[Middleware] | Callable[[ASGIApp], ASGIApp],
        **options: Any,
    ) -> None:
        """Add middleware to the stack."""
        self._middleware.append(middleware_class)
        self._middleware_options.append(options)
    
    def build(self) -> ASGIApp:
        """Build the middleware chain."""
        app = self._app
        
        # Apply middleware in reverse order so first added is outermost
        for middleware_class, options in zip(
            reversed(self._middleware),
            reversed(self._middleware_options),
        ):
            if options:
                app = middleware_class(app, **options)
            else:
                app = middleware_class(app)
        
        return app
