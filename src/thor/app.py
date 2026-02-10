"""
Main Thor application class.
The central component that ties all framework features together.
"""

from collections.abc import Callable
from typing import Any

from thor.exceptions import HTTPException
from thor.lifespan import Lifespan, LifespanProtocolHandler
from thor.middleware import ErrorHandlerMiddleware, Middleware, MiddlewareStack
from thor.request import Request
from thor.response import JSONResponse, Response
from thor.routing import Route, Router
from thor.types import ASGIApp, Receive, RouteHandler, Scope, Send

# Minimum recommended secret key length (in characters)
_MIN_SECRET_KEY_LENGTH: int = 16

# Middleware classes that require a secret_key to function securely
_SECRET_REQUIRED_MIDDLEWARE: set[str] = {
    "SessionMiddleware",
    "CSRFMiddleware",
}


class Thor:
    """
    The Thor micro web framework application.
    
    Implements the Facade pattern - provides a simple interface
    to the complex subsystems (routing, middleware, lifespan, etc.).
    
    Also follows the Composition pattern - composed of Router,
    MiddlewareStack, and Lifespan components.
    
    Usage:
        app = Thor()
        
        @app.get("/")
        async def hello(request):
            return {"message": "Hello, World!"}
        
        # Run with: uvicorn main:app
    """
    
    def __init__(
        self,
        debug: bool = False,
        title: str = "Thor API",
        version: str = "1.0.0",
        secret_key: str | None = None,
    ) -> None:
        self.debug = debug
        self.title = title
        self.version = version
        
        # Validate secret_key strength when provided
        if secret_key is not None and len(secret_key) < _MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"secret_key must be at least {_MIN_SECRET_KEY_LENGTH} characters. "
                f"Use a cryptographically random value in production."
            )
        self.secret_key = secret_key
        
        # Core components
        self._router = Router()
        self._lifespan = Lifespan()
        self._middleware_stack = MiddlewareStack(self._handle_request)
        
        # Add default error handler
        self._middleware_stack.add(ErrorHandlerMiddleware, debug=debug)
        
        # Application state
        self.state = self._lifespan.state
        
        # Build flag
        self._app: ASGIApp | None = None
    
    # -------------------------------------------------------------------------
    # ASGI Interface
    # -------------------------------------------------------------------------
    
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI application entry point."""
        scope["app"] = self
        
        if scope["type"] == "lifespan":
            handler = LifespanProtocolHandler(self._get_app(), self._lifespan)
            await handler(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._handle_websocket(scope, receive, send)
        else:
            await self._get_app()(scope, receive, send)
    
    def _get_app(self) -> ASGIApp:
        """Get the built ASGI application with middleware."""
        if self._app is None:
            self._app = self._middleware_stack.build()
        return self._app
    
    async def _handle_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Handle an incoming HTTP request."""
        request = Request(scope, receive)
        
        # Find matching route
        route, path_params = self._router.match(request.path, request.method)
        
        # Add path params to scope
        scope["path_params"] = path_params
        
        # Call the route handler
        response = await route.handler(request, **path_params)
        
        # Convert response if needed
        if not isinstance(response, Response):
            if isinstance(response, dict) or isinstance(response, list):
                response = JSONResponse(response)
            elif isinstance(response, str):
                from thor.response import TextResponse
                response = TextResponse(response)
            elif response is None:
                from thor.response import TextResponse
                response = TextResponse("", status_code=204)
            else:
                response = JSONResponse(response)
        
        # Send the response
        await response(send)
    
    # -------------------------------------------------------------------------
    # Routing
    # -------------------------------------------------------------------------
    
    @property
    def routes(self) -> list[Route]:
        """Get all registered routes."""
        return self._router.routes
    
    def add_route(
        self,
        path: str,
        handler: RouteHandler,
        methods: list[str] | None = None,
        name: str | None = None,
    ) -> Route:
        """Add a route to the application."""
        return self._router.add_route(path, handler, methods, name)
    
    def include_router(self, router: Router, prefix: str = "") -> None:
        """Include an external router."""
        self._router.include_router(router, prefix)
    
    def get(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for GET routes."""
        return self._router.get(path, name)
    
    def post(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for POST routes."""
        return self._router.post(path, name)
    
    def put(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for PUT routes."""
        return self._router.put(path, name)
    
    def patch(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for PATCH routes."""
        return self._router.patch(path, name)
    
    def delete(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for DELETE routes."""
        return self._router.delete(path, name)
    
    def route(
        self,
        path: str,
        methods: list[str] | None = None,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for routes with custom methods."""
        return self._router.route(path, methods, name)
    
    def websocket(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable:
        """Decorator for WebSocket routes."""
        return self._router.websocket(path, name)

    async def _handle_websocket(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """Dispatch an incoming WebSocket connection."""
        from thor.websocket import WebSocket

        path = scope.get("path", "/")
        try:
            route, path_params = self._router.ws_match(path)
        except Exception:
            # Reject unknown WS paths
            await send({"type": "websocket.close", "code": 1008})
            return

        scope["path_params"] = path_params
        ws = WebSocket(scope, receive, send)
        await route.handler(ws, **path_params)
    
    # -------------------------------------------------------------------------
    # Middleware
    # -------------------------------------------------------------------------
    
    def add_middleware(
        self,
        middleware_class: type[Middleware] | Callable[[ASGIApp], ASGIApp],
        **options: Any,
    ) -> None:
        """
        Add middleware to the application.
        
        Raises:
            RuntimeError: If a security middleware is added without
                          a secret_key configured on the application.
        """
        class_name = getattr(middleware_class, "__name__", "")
        if class_name in _SECRET_REQUIRED_MIDDLEWARE and self.secret_key is None:
            raise RuntimeError(
                f"{class_name} requires a secret_key. "
                f"Pass secret_key= when creating your Thor() application."
            )
        self._middleware_stack.add(middleware_class, **options)
        self._app = None  # Reset built app
    
    # -------------------------------------------------------------------------
    # Lifespan
    # -------------------------------------------------------------------------
    
    def on_startup(self, handler: Callable[[], Any]) -> Callable[[], Any]:
        """Decorator to register a startup handler."""
        return self._lifespan.on_startup(handler)
    
    def on_shutdown(self, handler: Callable[[], Any]) -> Callable[[], Any]:
        """Decorator to register a shutdown handler."""
        return self._lifespan.on_shutdown(handler)
    
    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------
    
    def url_for(self, name: str, **path_params: Any) -> str:
        """
        Generate a URL for a named route.
        
        Args:
            name: The route name.
            **path_params: Path parameters to substitute.
            
        Returns:
            The generated URL path.
        """
        for route in self.routes:
            if route.name == name:
                path = route.path
                for param, value in path_params.items():
                    # Replace {param} or {param:type} patterns
                    import re
                    pattern = rf"\{{{param}(?::\w+)?\}}"
                    path = re.sub(pattern, str(value), path)
                return path
        
        raise ValueError(f"No route named '{name}'")
    
    def run(
        self,
        host: str = "localhost",
        port: int = 8000,
        reload: bool = False,
        workers: int = 1,
        log_level: str = "info",
    ) -> None:
        """
        Run the application using uvicorn.
        
        Args:
            host: Host to bind to.
            port: Port to bind to.
            reload: Enable auto-reload.
            workers: Number of worker processes.
            log_level: Logging level.
        """
        import uvicorn
        
        uvicorn.run(
            self,
            host=host,
            port=port,
            reload=reload,
            workers=workers,
            log_level=log_level,
        )
