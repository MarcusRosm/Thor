"""Tests for thor.request — body parsing, size limits, properties."""

import pytest

from thor.exceptions import PayloadTooLarge
from thor.request import DEFAULT_MAX_BODY_SIZE, Request

from tests.conftest import make_receive, make_scope


class TestRequestProperties:
    """Basic request property access."""

    def test_method(self) -> None:
        scope = make_scope(method="POST")
        req = Request(scope, make_receive())
        assert req.method == "POST"

    def test_path(self) -> None:
        req = Request(make_scope(path="/hello"), make_receive())
        assert req.path == "/hello"

    def test_headers(self) -> None:
        req = Request(
            make_scope(headers={"X-Custom": "val"}),
            make_receive(),
        )
        assert req.headers["x-custom"] == "val"

    def test_query_params(self) -> None:
        req = Request(
            make_scope(query_string="a=1&b=2"),
            make_receive(),
        )
        assert req.query_params["a"] == "1"
        assert req.query_params["b"] == "2"

    def test_cookies(self) -> None:
        req = Request(
            make_scope(headers={"Cookie": "foo=bar; baz=qux"}),
            make_receive(),
        )
        assert req.cookies["foo"] == "bar"
        assert req.cookies["baz"] == "qux"

    def test_url(self) -> None:
        req = Request(
            make_scope(path="/x", headers={"Host": "example.com"}, query_string="q=1"),
            make_receive(),
        )
        assert req.url == "http://example.com/x?q=1"


class TestRequestBody:
    """Body reading and size enforcement."""

    @pytest.mark.asyncio
    async def test_read_body(self) -> None:
        req = Request(make_scope(), make_receive(b"hello"))
        assert await req.body() == b"hello"

    @pytest.mark.asyncio
    async def test_read_json(self) -> None:
        req = Request(make_scope(), make_receive(b'{"key":"val"}'))
        assert (await req.json()) == {"key": "val"}

    @pytest.mark.asyncio
    async def test_body_cached(self) -> None:
        req = Request(make_scope(), make_receive(b"data"))
        b1 = await req.body()
        b2 = await req.body()
        assert b1 is b2

    @pytest.mark.asyncio
    async def test_payload_too_large_via_content_length(self) -> None:
        scope = make_scope(headers={"Content-Length": "999999999"})
        req = Request(scope, make_receive(b"x"), max_body_size=1024)
        with pytest.raises(PayloadTooLarge):
            await req.body()

    @pytest.mark.asyncio
    async def test_payload_too_large_via_streaming(self) -> None:
        big = b"x" * 2048
        req = Request(make_scope(), make_receive(big), max_body_size=1024)
        with pytest.raises(PayloadTooLarge):
            await req.body()

    @pytest.mark.asyncio
    async def test_zero_max_body_disables_limit(self) -> None:
        big = b"x" * 5000
        req = Request(make_scope(), make_receive(big), max_body_size=0)
        assert len(await req.body()) == 5000

    def test_default_max_body_size(self) -> None:
        assert DEFAULT_MAX_BODY_SIZE == 1_048_576
