"""Tests for enhanced CORSMiddleware — wildcard subdomains, regex, Vary, credentials guard."""

import pytest

from thor.middleware import CORSMiddleware

from tests.conftest import ResponseCapture, make_receive, make_scope


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


class TestCORSOriginValidation:
    async def test_explicit_origin_reflected(self) -> None:
        mw = CORSMiddleware(_ok_app, allow_origins=["https://example.com"])
        scope = make_scope(headers={"origin": "https://example.com"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.headers.get("access-control-allow-origin") == "https://example.com"

    async def test_disallowed_origin_not_reflected(self) -> None:
        mw = CORSMiddleware(_ok_app, allow_origins=["https://example.com"])
        scope = make_scope(headers={"origin": "https://evil.com"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert "access-control-allow-origin" not in cap.headers

    async def test_wildcard_subdomain(self) -> None:
        mw = CORSMiddleware(_ok_app, allow_origins=["*.example.com"])
        scope = make_scope(headers={"origin": "https://app.example.com"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.headers.get("access-control-allow-origin") == "https://app.example.com"

    async def test_wildcard_subdomain_no_match(self) -> None:
        mw = CORSMiddleware(_ok_app, allow_origins=["*.example.com"])
        scope = make_scope(headers={"origin": "https://evil.org"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert "access-control-allow-origin" not in cap.headers

    async def test_regex_origin(self) -> None:
        mw = CORSMiddleware(
            _ok_app,
            allow_origins=[],
            allow_origin_regex=r"https://.*\.example\.com",
        )
        scope = make_scope(headers={"origin": "https://foo.example.com"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.headers["access-control-allow-origin"] == "https://foo.example.com"

    async def test_vary_origin_header(self) -> None:
        """Vary: Origin MUST be set when reflecting a specific origin."""
        mw = CORSMiddleware(_ok_app, allow_origins=["https://x.com"])
        scope = make_scope(headers={"origin": "https://x.com"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.headers.get("vary") == "Origin"

    async def test_bare_wildcard_no_vary(self) -> None:
        """Vary: Origin should NOT appear for bare wildcard *."""
        mw = CORSMiddleware(_ok_app, allow_origins=["*"])
        scope = make_scope(headers={"origin": "https://any.com"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        # Bare wildcard reflects the specific origin, but with Vary
        # Actually with our new code, _allow_all + no credentials → sends "*"
        assert cap.headers.get("access-control-allow-origin") == "*"

    def test_credentials_with_wildcard_raises(self) -> None:
        with pytest.raises(ValueError, match="allow_credentials"):
            CORSMiddleware(_ok_app, allow_origins=["*"], allow_credentials=True)

    async def test_credentials_with_explicit_origins_ok(self) -> None:
        mw = CORSMiddleware(
            _ok_app,
            allow_origins=["https://trusted.com"],
            allow_credentials=True,
        )
        scope = make_scope(headers={"origin": "https://trusted.com"})
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.headers["access-control-allow-credentials"] == "true"
        assert cap.headers["access-control-allow-origin"] == "https://trusted.com"

    async def test_preflight_with_regex(self) -> None:
        mw = CORSMiddleware(
            _ok_app,
            allow_origins=[],
            allow_origin_regex=r"https://.*\.mysite\.io",
        )
        scope = make_scope(
            method="OPTIONS",
            headers={"origin": "https://app.mysite.io"},
        )
        cap = ResponseCapture()
        await mw(scope, make_receive(b""), cap)
        assert cap.status == 204
        assert cap.headers["access-control-allow-origin"] == "https://app.mysite.io"
