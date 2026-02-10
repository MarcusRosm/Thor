"""Tests for thor.lifespan — Lifespan manager and LifespanProtocolHandler."""

import asyncio

import pytest

from thor.lifespan import Lifespan, LifespanProtocolHandler, LifespanState


class TestLifespanState:
    def test_get_set_contains(self) -> None:
        s = LifespanState()
        s["db"] = "connected"
        assert s["db"] == "connected"
        assert "db" in s

    def test_delete(self) -> None:
        s = LifespanState()
        s["key"] = "val"
        del s["key"]
        assert "key" not in s

    def test_get_default(self) -> None:
        s = LifespanState()
        assert s.get("missing", 42) == 42


class TestLifespan:
    async def test_startup_shutdown_handlers(self) -> None:
        events: list[str] = []
        ls = Lifespan()

        @ls.on_startup
        async def start():
            events.append("started")

        @ls.on_shutdown
        async def stop():
            events.append("stopped")

        async with ls(ls.state):
            assert events == ["started"]
        assert events == ["started", "stopped"]

    async def test_context_decorator(self) -> None:
        from contextlib import asynccontextmanager

        events: list[str] = []
        ls = Lifespan()

        @ls.context
        @asynccontextmanager
        async def ctx(state):
            events.append("enter")
            yield
            events.append("exit")

        async with ls(ls.state):
            assert events == ["enter"]
        assert events == ["enter", "exit"]


class TestLifespanProtocolHandler:
    def _make_handler(
        self,
        lifespan: Lifespan | None = None,
        shutdown_timeout: float = 1.0,
    ) -> LifespanProtocolHandler:
        async def noop_app(scope, receive, send):
            pass

        return LifespanProtocolHandler(
            noop_app,
            lifespan=lifespan,
            shutdown_timeout=shutdown_timeout,
        )

    async def test_initial_state(self) -> None:
        h = self._make_handler()
        assert h.inflight_requests == 0
        assert not h.is_shutting_down

    async def test_inflight_tracking(self) -> None:
        results: list[int] = []

        async def slow_app(scope, receive, send):
            results.append(1)
            await asyncio.sleep(0.05)

        h = LifespanProtocolHandler(slow_app, shutdown_timeout=1.0)
        scope = {"type": "http"}
        recv = lambda: asyncio.sleep(0)  # noqa: E731
        send = lambda msg: asyncio.sleep(0)  # noqa: E731

        # Launch a request
        task = asyncio.create_task(h(scope, recv, send))
        await asyncio.sleep(0.01)
        assert h.inflight_requests == 1
        await task
        assert h.inflight_requests == 0

    async def test_state_injected_into_scope(self) -> None:
        captured: dict = {}

        async def capture_app(scope, receive, send):
            captured["state"] = scope.get("state")

        h = LifespanProtocolHandler(capture_app)
        h.state["greeting"] = "hi"
        await h({"type": "http"}, lambda: asyncio.sleep(0), lambda m: asyncio.sleep(0))
        assert captured["state"]["greeting"] == "hi"

    async def test_drain_with_no_inflight(self) -> None:
        """_drain_requests should return immediately when no in-flight reqs."""
        h = self._make_handler(shutdown_timeout=0.5)
        # Should complete quickly
        await asyncio.wait_for(h._drain_requests(), timeout=1.0)
