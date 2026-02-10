"""Tests for thor.csrf — CSRFMiddleware token validation."""

import pytest

from thor.middleware.csrf import CSRFMiddleware, SAFE_METHODS
from tests.conftest import ResponseCapture, make_receive, make_scope


async def _ok_app(scope, receive, send):
    """Trivial ASGI app that returns 200."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


SECRET = "csrf-test-secret-key-1234"


class TestCSRFMiddleware:
    async def test_safe_method_passes(self) -> None:
        mw = CSRFMiddleware(_ok_app, secret_key=SECRET)
        scope = make_scope(method="GET", path="/anything")
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 200

    async def test_unsafe_without_token_rejected(self) -> None:
        mw = CSRFMiddleware(_ok_app, secret_key=SECRET)
        scope = make_scope(method="POST", path="/submit")
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 403

    async def test_unsafe_with_valid_header_token(self) -> None:
        token = "my-csrf-token"
        mw = CSRFMiddleware(_ok_app, secret_key=SECRET)
        # Simulate a request that already has the CSRF cookie *and* header
        scope = make_scope(
            method="POST",
            path="/submit",
            headers={
                "cookie": f"thor_csrf={token}",
                "x-csrf-token": token,
            },
        )
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 200

    async def test_token_mismatch_rejected(self) -> None:
        mw = CSRFMiddleware(_ok_app, secret_key=SECRET)
        scope = make_scope(
            method="POST",
            path="/submit",
            headers={
                "cookie": "thor_csrf=real-token",
                "x-csrf-token": "wrong-token",
            },
        )
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 403

    async def test_exclude_paths(self) -> None:
        mw = CSRFMiddleware(
            _ok_app,
            secret_key=SECRET,
            exclude_paths=["/api/webhook"],
        )
        scope = make_scope(method="POST", path="/api/webhook")
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 200

    async def test_csrf_cookie_set_on_response(self) -> None:
        mw = CSRFMiddleware(_ok_app, secret_key=SECRET)
        scope = make_scope(method="GET", path="/page")
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert "set-cookie" in cap.headers
        assert "thor_csrf=" in cap.headers["set-cookie"]

    async def test_generate_token_length(self) -> None:
        mw = CSRFMiddleware(_ok_app, secret_key=SECRET)
        tok = mw.generate_token()
        # token_urlsafe(32) → ~43 chars
        assert len(tok) > 20
