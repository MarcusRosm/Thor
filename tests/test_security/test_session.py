"""Tests for thor.session — backends, Session wrapper, SessionMiddleware."""

import os
import tempfile

import pytest

from thor.session import (
    FileSessionBackend,
    InMemorySessionBackend,
    Session,
    SessionData,
    SessionMiddleware,
)

from tests.conftest import ResponseCapture, make_receive, make_scope


# ---------------------------------------------------------------------------
# SessionData / Session wrapper
# ---------------------------------------------------------------------------


class TestSession:
    def test_getsetdel(self) -> None:
        sd = SessionData()
        s = Session(sd)
        s["key"] = "val"
        assert s["key"] == "val"
        assert len(s) == 1
        del s["key"]
        assert len(s) == 0

    def test_is_modified(self) -> None:
        sd = SessionData()
        s = Session(sd)
        assert not s.is_modified
        s["x"] = 1
        assert s.is_modified

    def test_flash(self) -> None:
        sd = SessionData()
        s = Session(sd)
        s.flash("msg", "hello")
        assert s.get_flash("msg") == "hello"
        # Second read should return default
        assert s.get_flash("msg", "gone") == "gone"

    def test_clear(self) -> None:
        sd = SessionData(data={"a": 1, "b": 2})
        s = Session(sd)
        s.clear()
        assert len(s) == 0
        assert s.is_modified


# ---------------------------------------------------------------------------
# InMemorySessionBackend
# ---------------------------------------------------------------------------


class TestInMemorySessionBackend:
    @pytest.fixture
    def backend(self) -> InMemorySessionBackend:
        return InMemorySessionBackend()

    async def test_save_and_load(self, backend: InMemorySessionBackend) -> None:
        sd = SessionData(data={"user": "alice"})
        await backend.save("s1", sd)
        loaded = await backend.load("s1")
        assert loaded is not None
        assert loaded.data["user"] == "alice"

    async def test_load_missing(self, backend: InMemorySessionBackend) -> None:
        assert await backend.load("nonexistent") is None

    async def test_delete(self, backend: InMemorySessionBackend) -> None:
        await backend.save("s1", SessionData())
        await backend.delete("s1")
        assert await backend.load("s1") is None

    async def test_cleanup(self, backend: InMemorySessionBackend) -> None:
        import time

        old = SessionData(accessed_at=time.time() - 1000)
        fresh = SessionData(accessed_at=time.time())
        await backend.save("old", old)
        await backend.save("fresh", fresh)
        await backend.cleanup(max_age=500)
        assert await backend.load("old") is None
        assert await backend.load("fresh") is not None


# ---------------------------------------------------------------------------
# FileSessionBackend
# ---------------------------------------------------------------------------


class TestFileSessionBackend:
    @pytest.fixture
    def backend(self, tmp_path: str) -> FileSessionBackend:
        return FileSessionBackend(directory=str(tmp_path))

    async def test_save_and_load(self, backend: FileSessionBackend) -> None:
        sd = SessionData(data={"colour": "blue"})
        await backend.save("sid1", sd)
        loaded = await backend.load("sid1")
        assert loaded is not None
        assert loaded.data["colour"] == "blue"

    async def test_load_missing(self, backend: FileSessionBackend) -> None:
        assert await backend.load("nope") is None

    async def test_delete(self, backend: FileSessionBackend) -> None:
        await backend.save("sid1", SessionData())
        await backend.delete("sid1")
        assert await backend.load("sid1") is None

    async def test_id_sanitisation(self, backend: FileSessionBackend) -> None:
        """Characters outside [a-zA-Z0-9_-] are stripped."""
        sd = SessionData(data={"x": 1})
        await backend.save("../../etc/passwd", sd)
        # Sanitised id: "etcpasswd"
        loaded = await backend.load("../../etc/passwd")
        assert loaded is not None
        assert loaded.data["x"] == 1

    async def test_empty_id_raises(self, backend: FileSessionBackend) -> None:
        with pytest.raises(ValueError):
            await backend.save("../../../", SessionData())

    async def test_cleanup(self, backend: FileSessionBackend) -> None:
        import time

        old = SessionData(data={}, accessed_at=time.time() - 5000)
        fresh = SessionData(data={}, accessed_at=time.time())
        await backend.save("old", old)
        await backend.save("fresh", fresh)
        await backend.cleanup(max_age=1000)
        assert await backend.load("old") is None
        assert await backend.load("fresh") is not None


# ---------------------------------------------------------------------------
# SessionMiddleware
# ---------------------------------------------------------------------------


class TestSessionMiddleware:
    async def test_sets_session_cookie(self) -> None:
        """Middleware should inject a Set-Cookie header with the session id."""

        async def inner(scope, receive, send):
            # Write something so the session is "modified"
            scope["session"]["user"] = "testuser"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = SessionMiddleware(inner, secret_key="a-nice-long-secret-key")
        scope = make_scope()
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 200
        # Should contain the session cookie
        assert "set-cookie" in cap.headers
        assert "thor_session=" in cap.headers["set-cookie"]
