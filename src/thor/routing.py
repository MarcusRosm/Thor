"""
Routing system for Thor framework.
Implements URL pattern matching and handler dispatch.

Uses a radix tree (compact trie) for O(path-length) route lookup
instead of linear scanning through all registered routes.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional, Match, AnyStr, Pattern

from thor.exceptions import MethodNotAllowed, NotFound, RoutingError
from thor.types import RouteHandler


# Pattern for extracting path parameters: {param} or {param:type}
PATH_PARAM_PATTERN: Pattern[str] = re.compile(r"\{(\w+)(?::(\w+))?\}")

# Type patterns for path parameter matching
TYPE_PATTERNS: dict[str, str] = {
    "int": r"\d+",
    "str": r"[^/]+",
    "path": r".+",
    "uuid": r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
    "slug": r"[a-z0-9]+(?:-[a-z0-9]+)*",
}

# Type converters
TYPE_CONVERTERS: dict[str, Callable[[str], Any]] = {
    "int": int,
    "str": str,
    "path": str,
    "uuid": str,
    "slug": str,
}


@dataclass(slots=True)
class Route:
    """
    Represents a single route in the application.
    
    Follows Single Responsibility Principle - handles route matching only.
    """
    
    path: str
    handler: RouteHandler
    methods: set[str] = field(default_factory=lambda: {"GET"})
    name: str | None = None
    _pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _param_types: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    
    def __post_init__(self) -> None:
        """Compile the route pattern."""
        self._compile_pattern()
    
    def _compile_pattern(self) -> None:
        """Convert path pattern to regex."""
        pattern = self.path
        self._param_types = {}
        
        def replace_param(match: re.Match[str]) -> str:
            param_name = match.group(1)
            param_type = match.group(2) or "str"
            
            if param_type not in TYPE_PATTERNS:
                raise RoutingError(f"Unknown parameter type: {param_type}")
            
            self._param_types[param_name] = param_type
            return f"(?P<{param_name}>{TYPE_PATTERNS[param_type]})"
        
        regex_pattern = PATH_PARAM_PATTERN.sub(replace_param, pattern)
        regex_pattern = f"^{regex_pattern}$"
        self._pattern = re.compile(regex_pattern)
    
    def match(self, path: str) -> dict[str, Any] | None:
        """
        Match a path against this route's pattern.
        Returns path parameters if matched, None otherwise.
        """
        if self._pattern is None:
            return None
        
        match = self._pattern.match(path)
        if not match:
            return None
        
        params: dict[str, Any] = {}
        for name, value in match.groupdict().items():
            param_type = self._param_types.get(name, "str")
            converter = TYPE_CONVERTERS.get(param_type, str)
            try:
                params[name] = converter(value)
            except (ValueError, TypeError):
                return None
        
        return params


# ---------------------------------------------------------------------------
# Radix tree for O(path-length) route resolution
# ---------------------------------------------------------------------------


class _RadixNode:
    """A single node in the radix tree."""

    __slots__ = ("segment", "children", "param_child", "routes")

    def __init__(self, segment: str = "") -> None:
        self.segment: str = segment
        # Static children keyed by the first character of their segment
        self.children: dict[str, "_RadixNode"] = {}
        # At most one parametric child (covers {param} / {param:type})
        self.param_child: "_RadixNode | None" = None
        # Routes that terminate at this node (may have different methods)
        self.routes: list[Route] = []


class RadixTree:
    """
    Compact prefix tree (radix tree) for fast route lookup.

    Static path segments are resolved via dictionary lookup.
    Parametric segments (``{name}`` / ``{name:type}``) are stored as
    a single child per node and matched via regex at lookup time.

    Complexity: O(number-of-segments) per lookup instead of
    O(total-routes).
    """

    def __init__(self) -> None:
        self._root = _RadixNode()

    # ------------------------------------------------------------------
    # Insertion
    # ------------------------------------------------------------------

    def insert(self, route: Route) -> None:
        """Insert a route into the tree."""
        segments = self._split(route.path)
        node = self._root

        for seg in segments:
            if self._is_param(seg):
                if node.param_child is None:
                    node.param_child = _RadixNode(seg)
                node = node.param_child
            else:
                if seg not in node.children:
                    node.children[seg] = _RadixNode(seg)
                node = node.children[seg]

        node.routes.append(route)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def search(self, path: str, method: str) -> tuple[Route, dict[str, Any]]:
        """
        Find a matching route.

        Returns ``(route, params)`` on success.
        Raises ``NotFound`` or ``MethodNotAllowed``.
        """
        segments = self._split(path)
        # (node, segment_index, accumulated_params)
        stack: list[tuple[_RadixNode, int, dict[str, Any]]] = [
            (self._root, 0, {}),
        ]

        method_matched_route: Route | None = None

        while stack:
            node, idx, params = stack.pop()

            if idx == len(segments):
                # We've consumed every segment — check for terminal routes
                for route in node.routes:
                    if method in route.methods:
                        return route, params
                    method_matched_route = method_matched_route or route
                continue

            seg_value = segments[idx]

            # Push param first so static (pushed second) is popped first (LIFO)
            # 1. Try parametric child
            if node.param_child is not None:
                pnode = node.param_child
                # Extract param name + type from the template segment
                # pyrefly: ignore [bad-assignment]
                m: Optional[Match[AnyStr]] = PATH_PARAM_PATTERN.fullmatch(pnode.segment)
                if m:
                    pname = m.group(1)
                    ptype = m.group(2) or "str"
                    # pyrefly: ignore [no-matching-overload]
                    type_re = TYPE_PATTERNS.get(ptype, TYPE_PATTERNS["str"])
                    if re.fullmatch(type_re, seg_value):
                        # pyrefly: ignore [no-matching-overload]
                        converter = TYPE_CONVERTERS.get(ptype, str)
                        try:
                            new_params = dict(params)
                            # pyrefly: ignore [unsupported-operation]
                            new_params[pname] = converter(seg_value)
                            stack.append((pnode, idx + 1, new_params))
                        except (ValueError, TypeError):
                            pass

            # 2. Try static child (pushed after param so it's popped first — LIFO)
            if seg_value in node.children:
                stack.append((node.children[seg_value], idx + 1, dict(params)))

        if method_matched_route is not None:
            raise MethodNotAllowed(f"Method {method} not allowed for {path}")
        raise NotFound(f"No route found for {path}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split(path: str) -> list[str]:
        """Split a path into non-empty segments."""
        return [s for s in path.split("/") if s]

    @staticmethod
    def _is_param(segment: str) -> bool:
        return segment.startswith("{") and segment.endswith("}")


class Router:
    """
    URL Router with support for nested routes and middleware.

    Implements the Composite pattern for nested routing.
    Uses a :class:`RadixTree` internally for O(path-length) lookups.
    """

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix.rstrip("/")
        self._routes: list[Route] = []
        self._subrouters: list[tuple[str, "Router"]] = []
        self._tree: RadixTree = RadixTree()
        self._tree_dirty: bool = False
    
    @property
    def routes(self) -> list[Route]:
        """Get all registered routes including subrouter routes."""
        all_routes: list[Route] = list(self._routes)
        
        for prefix, subrouter in self._subrouters:
            for route in subrouter.routes:
                full_path = f"{prefix}{route.path}"
                all_routes.append(Route(
                    path=full_path,
                    handler=route.handler,
                    methods=route.methods,
                    name=route.name,
                ))
        
        return all_routes
    
    def add_route(
        self,
        path: str,
        handler: RouteHandler,
        methods: list[str] | None = None,
        name: str | None = None,
    ) -> Route:
        """Add a route to the router."""
        full_path = f"{self._prefix}{path}" if self._prefix else path
        methods_set = set(m.upper() for m in (methods or ["GET"]))
        
        route = Route(
            path=full_path,
            handler=handler,
            methods=methods_set,
            name=name,
        )
        self._routes.append(route)
        self._tree.insert(route)
        self._tree_dirty = False  # Inserted directly — tree is up to date
        return route
    
    def include_router(self, router: "Router", prefix: str = "") -> None:
        """Include another router with an optional prefix."""
        full_prefix = f"{self._prefix}{prefix}"
        self._subrouters.append((full_prefix, router))
        self._tree_dirty = True

    def _rebuild_tree(self) -> None:
        """Rebuild the radix tree from the current route list."""
        tree = RadixTree()
        for route in self.routes:
            tree.insert(route)
        self._tree = tree
        self._tree_dirty = False

    def match(self, path: str, method: str) -> tuple[Route, dict[str, Any]]:
        """
        Find a matching route for the given path and method.

        Uses the radix tree for O(path-length) lookup.
        Raises NotFound or MethodNotAllowed if no match.
        """
        if self._tree_dirty:
            self._rebuild_tree()
        return self._tree.search(path, method.upper())
    
    # Decorator shortcuts
    def get(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for GET routes."""
        def decorator(handler: RouteHandler) -> RouteHandler:
            self.add_route(path, handler, methods=["GET"], name=name)
            return handler
        return decorator
    
    def post(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for POST routes."""
        def decorator(handler: RouteHandler) -> RouteHandler:
            self.add_route(path, handler, methods=["POST"], name=name)
            return handler
        return decorator
    
    def put(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for PUT routes."""
        def decorator(handler: RouteHandler) -> RouteHandler:
            self.add_route(path, handler, methods=["PUT"], name=name)
            return handler
        return decorator
    
    def patch(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for PATCH routes."""
        def decorator(handler: RouteHandler) -> RouteHandler:
            self.add_route(path, handler, methods=["PATCH"], name=name)
            return handler
        return decorator
    
    def delete(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for DELETE routes."""
        def decorator(handler: RouteHandler) -> RouteHandler:
            self.add_route(path, handler, methods=["DELETE"], name=name)
            return handler
        return decorator
    
    def route(
        self,
        path: str,
        methods: list[str] | None = None,
        name: str | None = None,
    ) -> Callable[[RouteHandler], RouteHandler]:
        """Decorator for routes with custom methods."""
        def decorator(handler: RouteHandler) -> RouteHandler:
            self.add_route(path, handler, methods=methods, name=name)
            return handler
        return decorator

    # ------------------------------------------------------------------
    # WebSocket routes
    # ------------------------------------------------------------------

    def add_websocket_route(
        self,
        path: str,
        handler: Any,
        name: str | None = None,
    ) -> Route:
        """Register a WebSocket endpoint."""
        full_path = f"{self._prefix}{path}" if self._prefix else path
        route = Route(
            path=full_path,
            handler=handler,
            methods={"WEBSOCKET"},
            name=name,
        )
        self._routes.append(route)
        self._tree.insert(route)
        self._tree_dirty = False
        return route

    def websocket(
        self,
        path: str,
        name: str | None = None,
    ) -> Callable:
        """Decorator for WebSocket routes."""
        def decorator(handler: Any) -> Any:
            self.add_websocket_route(path, handler, name=name)
            return handler
        return decorator

    def ws_match(self, path: str) -> tuple[Route, dict[str, Any]]:
        """Find a matching WebSocket route. Raises NotFound."""
        if self._tree_dirty:
            self._rebuild_tree()
        return self._tree.search(path, "WEBSOCKET")
