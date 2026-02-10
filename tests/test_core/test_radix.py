"""Tests for the radix tree router."""

import pytest

from thor.exceptions import MethodNotAllowed, NotFound
from thor.routing import RadixTree, Route, Router


async def _handler(request):
    return "ok"


class TestRadixTree:
    def test_static_route(self) -> None:
        tree = RadixTree()
        route = Route(path="/hello", handler=_handler, methods={"GET"})
        tree.insert(route)
        found, params = tree.search("/hello", "GET")
        assert found is route
        assert params == {}

    def test_param_route(self) -> None:
        tree = RadixTree()
        route = Route(path="/users/{id:int}", handler=_handler, methods={"GET"})
        tree.insert(route)
        found, params = tree.search("/users/42", "GET")
        assert found is route
        assert params == {"id": 42}

    def test_no_match(self) -> None:
        tree = RadixTree()
        route = Route(path="/x", handler=_handler, methods={"GET"})
        tree.insert(route)
        with pytest.raises(NotFound):
            tree.search("/y", "GET")

    def test_method_not_allowed(self) -> None:
        tree = RadixTree()
        route = Route(path="/data", handler=_handler, methods={"GET"})
        tree.insert(route)
        with pytest.raises(MethodNotAllowed):
            tree.search("/data", "DELETE")

    def test_multiple_params(self) -> None:
        tree = RadixTree()
        route = Route(path="/org/{org}/repo/{repo}", handler=_handler, methods={"GET"})
        tree.insert(route)
        found, params = tree.search("/org/acme/repo/thor", "GET")
        assert params == {"org": "acme", "repo": "thor"}

    def test_uuid_param(self) -> None:
        tree = RadixTree()
        route = Route(
            path="/items/{item_id:uuid}",
            handler=_handler,
            methods={"GET"},
        )
        tree.insert(route)
        uid = "550e8400-e29b-41d4-a716-446655440000"
        found, params = tree.search(f"/items/{uid}", "GET")
        assert params["item_id"] == uid

    def test_static_preferred_over_param(self) -> None:
        """Static child should be tried alongside parametric child."""
        tree = RadixTree()
        static = Route(path="/users/me", handler=_handler, methods={"GET"})
        param = Route(path="/users/{id}", handler=_handler, methods={"GET"})
        tree.insert(static)
        tree.insert(param)
        found, params = tree.search("/users/me", "GET")
        assert found is static
        assert params == {}


class TestRouterRadixIntegration:
    """Ensure Router.match() goes through the radix tree."""

    def test_basic_match(self) -> None:
        r = Router()
        r.add_route("/ping", _handler, methods=["GET"])
        route, params = r.match("/ping", "GET")
        assert route.path == "/ping"
        assert params == {}

    def test_subrouter_triggers_rebuild(self) -> None:
        parent = Router()
        child = Router()
        child.add_route("/bar", _handler, methods=["GET"])
        parent.include_router(child, prefix="/foo")
        # Should trigger tree rebuild
        route, params = parent.match("/foo/bar", "GET")
        assert route.path == "/foo/bar"

    def test_websocket_route(self) -> None:
        r = Router()
        r.add_websocket_route("/ws", _handler)
        route, params = r.ws_match("/ws")
        assert route.path == "/ws"
