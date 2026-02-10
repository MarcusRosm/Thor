"""Tests for thor.app — Thor application integration tests."""

import pytest

from thor.app import Thor, _MIN_SECRET_KEY_LENGTH, _SECRET_REQUIRED_MIDDLEWARE
from thor.middleware import Middleware, CSRFMiddleware
from thor.request import Request
from thor.response import JSONResponse, TextResponse
from thor.session import SessionMiddleware

from tests.conftest import ResponseCapture, make_receive, make_scope


class TestSecretKeyValidation:
    def test_short_secret_raises(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            Thor(secret_key="short")

    def test_none_secret_allowed(self) -> None:
        app = Thor(secret_key=None)
        assert app.secret_key is None

    def test_valid_secret(self) -> None:
        app = Thor(secret_key="a" * _MIN_SECRET_KEY_LENGTH)
        assert app.secret_key is not None


class TestAddMiddlewareGuard:
    def test_session_middleware_without_secret_raises(self) -> None:
        app = Thor()
        with pytest.raises(RuntimeError, match="secret_key"):
            app.add_middleware(SessionMiddleware, secret_key="unused")

    def test_csrf_middleware_without_secret_raises(self) -> None:
        app = Thor()
        with pytest.raises(RuntimeError, match="secret_key"):
            app.add_middleware(CSRFMiddleware, secret_key="unused")

    def test_session_middleware_with_secret_ok(self) -> None:
        app = Thor(secret_key="a" * _MIN_SECRET_KEY_LENGTH)
        app.add_middleware(SessionMiddleware, secret_key="a" * 20)


class TestRouteRegistration:
    def test_decorator_registers_route(self) -> None:
        app = Thor()

        @app.get("/hello")
        async def hello(request):
            return {"msg": "hi"}

        assert any(r.path == "/hello" for r in app.routes)

    def test_url_for(self) -> None:
        app = Thor()
        app.add_route("/users/{id:int}", lambda r: None, name="user_detail")
        url = app.url_for("user_detail", id=42)
        assert url == "/users/42"

    def test_url_for_unknown_raises(self) -> None:
        app = Thor()
        with pytest.raises(ValueError, match="No route named"):
            app.url_for("nonexistent")


class TestRequestHandling:
    async def test_dict_response_conversion(self) -> None:
        app = Thor()

        @app.get("/data")
        async def handler(request):
            return {"key": "value"}

        scope = make_scope(method="GET", path="/data")
        cap = ResponseCapture()
        await app(scope, make_receive(b""), cap)
        assert cap.status == 200
        assert b'"key"' in cap.body

    async def test_string_response_conversion(self) -> None:
        app = Thor()

        @app.get("/text")
        async def handler(request):
            return "hello"

        scope = make_scope(method="GET", path="/text")
        cap = ResponseCapture()
        await app(scope, make_receive(b""), cap)
        assert cap.status == 200
        assert cap.body == b"hello"

    async def test_none_response_returns_204(self) -> None:
        app = Thor()

        @app.post("/fire")
        async def handler(request):
            return None

        scope = make_scope(method="POST", path="/fire")
        cap = ResponseCapture()
        await app(scope, make_receive(b""), cap)
        assert cap.status == 204

    async def test_404_for_unknown_route(self) -> None:
        app = Thor()

        scope = make_scope(method="GET", path="/nope")
        cap = ResponseCapture()
        await app(scope, make_receive(b""), cap)
        assert cap.status == 404

    async def test_405_for_wrong_method(self) -> None:
        app = Thor()

        @app.get("/only-get")
        async def handler(request):
            return "ok"

        scope = make_scope(method="DELETE", path="/only-get")
        cap = ResponseCapture()
        await app(scope, make_receive(b""), cap)
        assert cap.status == 405
