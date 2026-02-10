"""Tests for thor.cookies — signing, unsigning, parsing."""

from thor.cookies import CookieOptions, SecureCookie, format_set_cookie, parse_cookies


class TestSecureCookie:
    def test_sign_and_unsign(self) -> None:
        sc = SecureCookie("secret-key-for-tests")
        signed = sc.sign("hello")
        assert sc.unsign(signed) == "hello"

    def test_invalid_signature(self) -> None:
        sc = SecureCookie("secret-key-for-tests")
        assert sc.unsign("tampered:value:badsig") is None

    def test_expired_signature(self) -> None:
        import time

        sc = SecureCookie("secret-key-for-tests")
        # Manually craft an old timestamp
        old_ts = str(int(time.time()) - 1000)
        value_with_ts = f"{old_ts}:testval"
        sig = sc._create_signature(value_with_ts)
        signed = f"{value_with_ts}:{sig}"

        # Should fail with max_age=1
        assert sc.unsign(signed, max_age=1) is None
        # Should succeed without max_age
        assert sc.unsign(signed) == "testval"

    def test_encode_decode(self) -> None:
        sc = SecureCookie("secret-key-for-tests")
        data = {"user": "admin", "role": "superuser"}
        encoded = sc.encode_value(data)
        decoded = sc.decode_value(encoded)
        assert decoded == data

    def test_generate_secret_key(self) -> None:
        key = SecureCookie.generate_secret_key()
        assert len(key) >= 32


class TestParseCookies:
    def test_basic(self) -> None:
        result = parse_cookies("a=1; b=2")
        assert result == {"a": "1", "b": "2"}

    def test_empty(self) -> None:
        assert parse_cookies("") == {}


class TestFormatSetCookie:
    def test_defaults(self) -> None:
        cookie = format_set_cookie("name", "val")
        assert cookie.startswith("name=val;")
        assert "HttpOnly" in cookie
        assert "Secure" in cookie

    def test_custom_options(self) -> None:
        opts = CookieOptions(max_age=3600, httponly=False, secure=False)
        cookie = format_set_cookie("x", "y", opts)
        assert "Max-Age=3600" in cookie
        assert "HttpOnly" not in cookie
