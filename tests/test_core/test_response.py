"""Tests for thor.response — rendering, streaming, FileResponse safety."""

import json
import os
import tempfile

import pytest

from thor.response import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    TextResponse,
)

from tests.conftest import ResponseCapture


class TestTextResponse:
    def test_render_string(self) -> None:
        r = TextResponse("hello")
        assert r.render() == b"hello"

    def test_render_none(self) -> None:
        assert TextResponse(None).render() == b""

    def test_render_bytes(self) -> None:
        assert TextResponse(b"raw").render() == b"raw"


class TestHTMLResponse:
    def test_media_type(self) -> None:
        assert HTMLResponse("<h1>hi</h1>").media_type == "text/html"

    def test_render(self) -> None:
        assert HTMLResponse("<b>ok</b>").render() == b"<b>ok</b>"


class TestJSONResponse:
    def test_render(self) -> None:
        r = JSONResponse({"a": 1})
        assert json.loads(r.render()) == {"a": 1}

    def test_null(self) -> None:
        assert JSONResponse(None).render() == b"null"

    @pytest.mark.asyncio
    async def test_send(self) -> None:
        cap = ResponseCapture()
        await JSONResponse({"ok": True}, status_code=201)(cap)
        assert cap.status == 201
        assert json.loads(cap.body) == {"ok": True}


class TestRedirectResponse:
    @pytest.mark.asyncio
    async def test_redirect(self) -> None:
        cap = ResponseCapture()
        await RedirectResponse("/new")(cap)
        assert cap.status == 307
        assert cap.headers["location"] == "/new"


class TestFileResponse:
    def test_streaming_and_content_length(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"hello world")
            path = f.name
        try:
            resp = FileResponse(path, base_directory=os.path.dirname(path))
            assert resp._headers["content-length"] == "11"
        finally:
            os.unlink(path)

    def test_path_traversal_blocked(self) -> None:
        with pytest.raises(ValueError, match="outside"):
            FileResponse("/etc/hosts", base_directory="/tmp")

    def test_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            FileResponse("/nonexistent/file.txt")

    @pytest.mark.asyncio
    async def test_sends_chunked(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"A" * 200)
            path = f.name
        try:
            cap = ResponseCapture()
            resp = FileResponse(path, chunk_size=64)
            await resp(cap)
            assert cap.status == 200
            # body should be complete (200 bytes)
            assert len(cap.body) == 200
        finally:
            os.unlink(path)
