"""Tests for thor.middleware — ErrorHandler, CORS, Timeout, Logging."""

import asyncio
import json

import pytest

from thor.exceptions import BadRequest, RequestTimeout
from thor.middleware import (
    CORSMiddleware,
    ErrorHandlerMiddleware,
    TimeoutMiddleware,
    RequestLoggingMiddleware,
)

from tests.conftest import ResponseCapture, make_receive, make_scope


# ---------------------------------------------------------------------------
# ErrorHandlerMiddleware
# ---------------------------------------------------------------------------

class TestErrorHandlerMiddleware:
    @pytest.mark.asyncio
    async def test_catches_http_exception(self) -> None:
        async def app(scope, receive, send):
            raise BadRequest("oops")

        mw = ErrorHandlerMiddleware(app, debug=False)
        cap = ResponseCapture()
        await mw(make_scope(), make_receive(), cap)

        assert cap.status == 400
        body = json.loads(cap.body)
        assert body["error"] == "oops"
        assert "request_id" in body

    @pytest.mark.asyncio
    async def test_never_leaks_internal_details(self) -> None:
        async def app(scope, receive, send):
            raise RuntimeError("secret database password 1234")

        mw = ErrorHandlerMiddleware(app, debug=True)  # debug=True on purpose
        cap = ResponseCapture()
        await mw(make_scope(), make_receive(), cap)

        assert cap.status == 500
        body = json.loads(cap.body)
        assert "secret" not in body["error"]
        assert body["error"] == "Internal Server Error"

    @pytest.mark.asyncio
    async def test_injects_request_id_header(self) -> None:
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = ErrorHandlerMiddleware(app)
        cap = ResponseCapture()
        await mw(make_scope(), make_receive(), cap)

        assert "x-request-id" in cap.headers
        assert len(cap.headers["x-request-id"]) > 0


# ---------------------------------------------------------------------------
# CORSMiddleware
# ---------------------------------------------------------------------------

class TestCORSMiddleware:
    @pytest.mark.asyncio
    async def test_adds_cors_headers(self) -> None:
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = CORSMiddleware(app, allow_origins=["https://example.com"])
        cap = ResponseCapture()
        scope = make_scope(headers={"Origin": "https://example.com"})
        await mw(scope, make_receive(), cap)

        assert cap.headers["access-control-allow-origin"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_preflight_returns_204(self) -> None:
        async def app(scope, receive, send):
            raise AssertionError("should not reach app")

        mw = CORSMiddleware(app)
        cap = ResponseCapture()
        scope = make_scope(method="OPTIONS", headers={"Origin": "https://x.com"})
        await mw(scope, make_receive(), cap)

        assert cap.status == 204


# ---------------------------------------------------------------------------
# TimeoutMiddleware
# ---------------------------------------------------------------------------

class TestTimeoutMiddleware:
    @pytest.mark.asyncio
    async def test_fast_request_succeeds(self) -> None:
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = TimeoutMiddleware(app, timeout=5.0)
        cap = ResponseCapture()
        await mw(make_scope(), make_receive(), cap)
        assert cap.status == 200

    @pytest.mark.asyncio
    async def test_slow_request_times_out(self) -> None:
        async def app(scope, receive, send):
            await asyncio.sleep(10)

        mw = TimeoutMiddleware(app, timeout=0.05)
        cap = ResponseCapture()
        with pytest.raises(RequestTimeout):
            await mw(make_scope(), make_receive(), cap)


# ---------------------------------------------------------------------------
# RequestLoggingMiddleware
# ---------------------------------------------------------------------------

class TestRequestLoggingMiddleware:
    @pytest.mark.asyncio
    async def test_logs_without_crashing(self) -> None:
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        mw = RequestLoggingMiddleware(app)
        cap = ResponseCapture()
        # Should not raise
        await mw(make_scope(), make_receive(), cap)
        assert cap.status == 200
