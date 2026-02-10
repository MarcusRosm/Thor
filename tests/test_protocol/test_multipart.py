"""Tests for thor.multipart — UploadFile and parse_multipart."""

import pytest

from thor.multipart import UploadFile, parse_multipart
from thor.request import Request

from tests.conftest import make_receive, make_scope


def _build_multipart(boundary: str, parts: list[dict]) -> bytes:
    """Helper to construct a multipart/form-data body."""
    lines: list[bytes] = []
    for part in parts:
        lines.append(f"--{boundary}\r\n".encode())
        if "filename" in part:
            lines.append(
                f'Content-Disposition: form-data; name="{part["name"]}"; '
                f'filename="{part["filename"]}"\r\n'.encode()
            )
            ct = part.get("content_type", "application/octet-stream")
            lines.append(f"Content-Type: {ct}\r\n".encode())
        else:
            lines.append(
                f'Content-Disposition: form-data; name="{part["name"]}"\r\n'.encode()
            )
        lines.append(b"\r\n")
        data = part["data"]
        lines.append(data if isinstance(data, bytes) else data.encode())
        lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())
    return b"".join(lines)


class TestUploadFile:
    async def test_read_and_size(self) -> None:
        uf = UploadFile(filename="test.txt")
        uf.file.write(b"hello world")
        await uf.seek(0)
        assert uf.size == 11
        data = await uf.read()
        assert data == b"hello world"

    def test_close(self) -> None:
        uf = UploadFile(filename="x.bin")
        uf.file.write(b"data")
        uf.close()
        assert uf.file.closed


class TestParseMultipart:
    def test_single_field(self) -> None:
        body = _build_multipart("BOUNDARY", [
            {"name": "username", "data": "alice"},
        ])
        fields, files = parse_multipart(body, "BOUNDARY")
        assert fields["username"] == "alice"
        assert files == []

    def test_single_file(self) -> None:
        body = _build_multipart("B", [
            {"name": "avatar", "filename": "photo.png", "data": b"\x89PNG", "content_type": "image/png"},
        ])
        fields, files = parse_multipart(body, "B")
        assert len(files) == 1
        assert files[0].filename == "photo.png"
        assert files[0].content_type == "image/png"
        assert files[0].file.read() == b"\x89PNG"

    def test_mixed_fields_and_files(self) -> None:
        body = _build_multipart("X", [
            {"name": "title", "data": "My Doc"},
            {"name": "doc", "filename": "a.pdf", "data": b"%PDF-1.4"},
        ])
        fields, files = parse_multipart(body, "X")
        assert fields["title"] == "My Doc"
        assert len(files) == 1
        assert files[0].filename == "a.pdf"

    def test_multiple_values_same_name(self) -> None:
        body = _build_multipart("Z", [
            {"name": "tag", "data": "python"},
            {"name": "tag", "data": "web"},
        ])
        fields, _files = parse_multipart(body, "Z")
        assert fields["tag"] == ["python", "web"]


class TestRequestMultipart:
    async def test_request_files(self) -> None:
        boundary = "testboundary"
        body = _build_multipart(boundary, [
            {"name": "file", "filename": "readme.md", "data": b"# Hello"},
        ])
        scope = make_scope(
            method="POST",
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        req = Request(scope, make_receive(body), max_body_size=0)
        files = await req.files()
        assert len(files) == 1
        assert files[0].filename == "readme.md"

    async def test_request_form_multipart(self) -> None:
        boundary = "fb"
        body = _build_multipart(boundary, [
            {"name": "name", "data": "Thor"},
        ])
        scope = make_scope(
            method="POST",
            headers={"content-type": f"multipart/form-data; boundary={boundary}"},
        )
        # form() should detect multipart and delegate
        req = Request(scope, make_receive(body), max_body_size=0)
        form = await req.form()
        assert form["name"] == "Thor"
