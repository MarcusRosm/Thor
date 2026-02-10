"""Tests for RateLimitMiddleware."""

import pytest

from thor.middleware import RateLimitMiddleware

from tests.conftest import ResponseCapture, make_receive, make_scope


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class TestRateLimitMiddleware:
    async def test_allows_under_limit(self) -> None:
        mw = RateLimitMiddleware(_ok_app, max_requests=5, window_seconds=60)
        scope = make_scope()
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 200

    async def test_injects_ratelimit_headers(self) -> None:
        mw = RateLimitMiddleware(_ok_app, max_requests=10, window_seconds=60)
        scope = make_scope()
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert "x-ratelimit-limit" in cap.headers
        assert cap.headers["x-ratelimit-limit"] == "10"
        assert "x-ratelimit-remaining" in cap.headers

    async def test_blocks_over_limit(self) -> None:
        mw = RateLimitMiddleware(_ok_app, max_requests=3, window_seconds=60)
        for _ in range(3):
            cap = ResponseCapture()
            await mw(make_scope(), make_receive(b""), cap)
            assert cap.status == 200

        # 4th request should be blocked
        cap = ResponseCapture()
        await mw(make_scope(), make_receive(b""), cap)
        assert cap.status == 429
        assert "retry-after" in cap.headers

    async def test_different_clients_tracked_separately(self) -> None:
        mw = RateLimitMiddleware(_ok_app, max_requests=1, window_seconds=60)

        scope_a = make_scope(extras={"client": ("10.0.0.1", 100)})
        scope_b = make_scope(extras={"client": ("10.0.0.2", 200)})

        cap_a = ResponseCapture()
        await mw(scope_a, make_receive(b""), cap_a)
        assert cap_a.status == 200

        cap_b = ResponseCapture()
        await mw(scope_b, make_receive(b""), cap_b)
        assert cap_b.status == 200

        # Second request from client A should be blocked
        cap_a2 = ResponseCapture()
        await mw(scope_a, make_receive(b""), cap_a2)
        assert cap_a2.status == 429
