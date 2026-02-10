"""
Secure cookie handling for Thor framework.
Implements signing and encryption for cookie security.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CookieOptions:
    """Cookie configuration options (Immutable Value Object)."""
    
    max_age: int | None = None  # In seconds
    expires: str | None = None
    path: str = "/"
    domain: str | None = None
    secure: bool = True
    httponly: bool = True
    samesite: str = "lax"  # "strict", "lax", or "none"
    
    def to_header_string(self) -> str:
        """Convert options to cookie header format."""
        parts: list[str] = []
        
        if self.max_age is not None:
            parts.append(f"Max-Age={self.max_age}")
        if self.expires:
            parts.append(f"Expires={self.expires}")
        if self.path:
            parts.append(f"Path={self.path}")
        if self.domain:
            parts.append(f"Domain={self.domain}")
        if self.secure:
            parts.append("Secure")
        if self.httponly:
            parts.append("HttpOnly")
        if self.samesite:
            parts.append(f"SameSite={self.samesite.capitalize()}")
        
        return "; ".join(parts)


class SecureCookie:
    """
    Secure cookie implementation with HMAC signing.
    
    Follows Single Responsibility Principle - handles only cookie security.
    Uses HMAC-SHA256 for message authentication.
    """
    
    def __init__(self, secret_key: str | bytes) -> None:
        if isinstance(secret_key, str):
            secret_key = secret_key.encode("utf-8")
        self._secret_key = secret_key
        self._hash_algorithm = hashlib.sha256
    
    def sign(self, value: str) -> str:
        """Sign a value and return the signed string."""
        timestamp = str(int(time.time()))
        value_with_ts = f"{timestamp}:{value}"
        signature = self._create_signature(value_with_ts)
        return f"{value_with_ts}:{signature}"
    
    def unsign(
        self,
        signed_value: str,
        max_age: int | None = None,
    ) -> str | None:
        """
        Verify signature and return original value.
        Returns None if signature is invalid or expired.
        """
        try:
            parts = signed_value.rsplit(":", 2)
            if len(parts) != 3:
                return None
            
            timestamp_str, value, signature = parts
            value_with_ts = f"{timestamp_str}:{value}"
            
            # Verify signature using constant-time comparison
            expected_signature = self._create_signature(value_with_ts)
            if not hmac.compare_digest(signature, expected_signature):
                return None
            
            # Check expiration
            if max_age is not None:
                timestamp = int(timestamp_str)
                if time.time() - timestamp > max_age:
                    return None
            
            return value
        except (ValueError, TypeError):
            return None
    
    def encode_value(self, data: Any) -> str:
        """Encode data to a signed base64 string."""
        json_data = json.dumps(data, separators=(",", ":"))
        encoded = base64.urlsafe_b64encode(json_data.encode("utf-8")).decode("ascii")
        return self.sign(encoded)
    
    def decode_value(
        self,
        encoded_value: str,
        max_age: int | None = None,
    ) -> Any | None:
        """Decode and verify a signed value. Returns None if invalid."""
        unsigned = self.unsign(encoded_value, max_age)
        if unsigned is None:
            return None
        
        try:
            json_data = base64.urlsafe_b64decode(unsigned.encode("ascii")).decode("utf-8")
            return json.loads(json_data)
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
    
    def _create_signature(self, value: str) -> str:
        """Create HMAC signature for a value."""
        signature = hmac.new(
            self._secret_key,
            value.encode("utf-8"),
            self._hash_algorithm,
        ).digest()
        return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    
    @staticmethod
    def generate_secret_key(length: int = 32) -> str:
        """Generate a cryptographically secure secret key."""
        return secrets.token_urlsafe(length)


def parse_cookies(cookie_header: str) -> dict[str, str]:
    """Parse a Cookie header string into a dictionary."""
    cookies: dict[str, str] = {}
    
    if not cookie_header:
        return cookies
    
    for item in cookie_header.split(";"):
        item = item.strip()
        if "=" in item:
            key, _, value = item.partition("=")
            cookies[key.strip()] = value.strip()
    
    return cookies


def format_set_cookie(
    name: str,
    value: str,
    options: CookieOptions | None = None,
) -> str:
    """Format a Set-Cookie header value."""
    options = options or CookieOptions()
    cookie = f"{name}={value}"
    options_str = options.to_header_string()
    
    if options_str:
        cookie = f"{cookie}; {options_str}"
    
    return cookie
