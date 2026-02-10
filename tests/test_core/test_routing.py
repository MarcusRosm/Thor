"""Tests for thor.routing — pattern matching, type conversion, subrouters."""

import pytest

from thor.exceptions import MethodNotAllowed, NotFound
from thor.routing import Route, Router


class TestRoute:
    def test_static_match(self) -> None:
        async def handler() -> None: ...
        route = Route("/hello", handler)
        assert route.match("/hello") == {}

    def test_no_match(self) -> None:
        async def handler() -> None: ...
        route = Route("/hello", handler)
        assert route.match("/world") is None

    def test_int_param(self) -> None:
        async def handler() -> None: ...
        route = Route("/users/{user_id:int}", handler)
        result = route.match("/users/42")
        assert result == {"user_id": 42}

    def test_uuid_param(self) -> None:
        async def handler() -> None: ...
        route = Route("/items/{item_id:uuid}", handler)
        result = route.match("/items/550e8400-e29b-41d4-a716-446655440000")
        assert result is not None
        assert result["item_id"] == "550e8400-e29b-41d4-a716-446655440000"

    def test_slug_param(self) -> None:
        async def handler() -> None: ...
        route = Route("/posts/{slug:slug}", handler)
        assert route.match("/posts/my-first-post") is not None
        assert route.match("/posts/CAPS") is None  # slugs are lowercase


class TestRouter:
    def test_add_route_and_match(self) -> None:
        router = Router()
        async def handler() -> None: ...
        router.add_route("/test", handler, methods=["GET"])
        route, params = router.match("/test", "GET")
        assert route.path == "/test"
        assert params == {}

    def test_method_not_allowed(self) -> None:
        router = Router()
        async def handler() -> None: ...
        router.add_route("/test", handler, methods=["GET"])
        with pytest.raises(MethodNotAllowed):
            router.match("/test", "POST")

    def test_not_found(self) -> None:
        router = Router()
        with pytest.raises(NotFound):
            router.match("/nope", "GET")

    def test_subrouter(self) -> None:
        main = Router()
        sub = Router(prefix="/api")
        async def handler() -> None: ...
        sub.add_route("/items", handler, methods=["GET"])
        main.include_router(sub)
        route, params = main.match("/api/items", "GET")
        assert route.path == "/api/items"

    def test_decorator_get(self) -> None:
        router = Router()

        @router.get("/deco")
        async def handler() -> None: ...

        route, _ = router.match("/deco", "GET")
        assert route.handler is handler
