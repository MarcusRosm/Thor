"""
Request handling for Thor framework.
Encapsulates all HTTP request data and parsing.
"""

import json
from collections.abc import Mapping
from functools import cached_property
from typing import Any
from urllib.parse import parse_qs, unquote

from thor.cookies import parse_cookies
from thor.types import Receive, Scope, State

# Default maximum request body size: 1 MB
DEFAULT_MAX_BODY_SIZE: int = 1_048_576


class Request:
    """
    HTTP Request wrapper.
    
    Follows Single Responsibility Principle - handles only request data.
    Uses lazy loading for body parsing to optimize performance.
    """
    
    def __init__(
        self,
        scope: Scope,
        receive: Receive,
        max_body_size: int = DEFAULT_MAX_BODY_SIZE,
    ) -> None:
        self._scope = scope
        self._receive = receive
        self._body: bytes | None = None
        self._body_consumed = False
        self._max_body_size = max_body_size
        self.state: State = {}
    
    @property
    def method(self) -> str:
        """HTTP method (GET, POST, etc.)."""
        return self._scope.get("method", "GET")
    
    @property
    def path(self) -> str:
        """Request path."""
        return self._scope.get("path", "/")
    
    @property
    def query_string(self) -> str:
        """Raw query string."""
        return self._scope.get("query_string", b"").decode("utf-8")
    
    @cached_property
    def query_params(self) -> Mapping[str, str | list[str]]:
        """Parsed query parameters."""
        params: dict[str, str | list[str]] = {}
        parsed = parse_qs(self.query_string, keep_blank_values=True)
        
        for key, values in parsed.items():
            if len(values) == 1:
                params[key] = values[0]
            else:
                params[key] = values
        
        return params
    
    @cached_property
    def headers(self) -> Mapping[str, str]:
        """Request headers as a dictionary."""
        headers: dict[str, str] = {}
        raw_headers = self._scope.get("headers", [])
        
        for name, value in raw_headers:
            header_name = name.decode("latin-1").lower()
            header_value = value.decode("latin-1")
            headers[header_name] = header_value
        
        return headers
    
    @cached_property
    def cookies(self) -> Mapping[str, str]:
        """Request cookies."""
        cookie_header = self.headers.get("cookie", "")
        return parse_cookies(cookie_header)
    
    @property
    def content_type(self) -> str:
        """Content-Type header value."""
        return self.headers.get("content-type", "")
    
    @property
    def content_length(self) -> int | None:
        """Content-Length header value."""
        length = self.headers.get("content-length")
        return int(length) if length else None
    
    @property
    def host(self) -> str:
        """Host header value."""
        return self.headers.get("host", "")
    
    @property
    def scheme(self) -> str:
        """URL scheme (http or https)."""
        return self._scope.get("scheme", "http")
    
    @property
    def client(self) -> tuple[str, int] | None:
        """Client address as (host, port) tuple."""
        client = self._scope.get("client")
        if client:
            return (client[0], client[1])
        return None
    
    @property
    def url(self) -> str:
        """Full URL."""
        url = f"{self.scheme}://{self.host}{self.path}"
        if self.query_string:
            url = f"{url}?{self.query_string}"
        return url
    
    @property
    def app(self) -> Any:
        """Reference to the application instance."""
        return self._scope.get("app")
    
    @property
    def path_params(self) -> dict[str, str]:
        """Path parameters extracted from URL patterns."""
        return self._scope.get("path_params", {})
    
    async def body(self) -> bytes:
        """
        Read and return the request body.
        
        Raises:
            PayloadTooLarge: If body exceeds max_body_size.
        """
        if self._body is not None:
            return self._body
        
        if self._body_consumed:
            return b""
        
        from thor.exceptions import PayloadTooLarge
        
        # Early rejection via Content-Length header
        if (
            self._max_body_size > 0
            and self.content_length is not None
            and self.content_length > self._max_body_size
        ):
            raise PayloadTooLarge(
                f"Request body too large. "
                f"Maximum allowed: {self._max_body_size} bytes"
            )
        
        chunks: list[bytes] = []
        total_size = 0
        
        while True:
            message = await self._receive()
            body = message.get("body", b"")
            if body:
                total_size += len(body)
                if self._max_body_size > 0 and total_size > self._max_body_size:
                    raise PayloadTooLarge(
                        f"Request body too large. "
                        f"Maximum allowed: {self._max_body_size} bytes"
                    )
                chunks.append(body)
            
            if not message.get("more_body", False):
                break
        
        self._body = b"".join(chunks)
        self._body_consumed = True
        return self._body
    
    async def text(self) -> str:
        """Read body as text."""
        body = await self.body()
        return body.decode("utf-8")
    
    async def json(self) -> Any:
        """Parse body as JSON."""
        text = await self.text()
        return json.loads(text) if text else None
    
    async def form(self) -> Mapping[str, str | list[str]]:
        """Parse body as form data (URL-encoded or multipart)."""
        if "multipart/form-data" in self.content_type:
            fields, _files = await self.multipart()
            return fields

        body = await self.text()
        parsed = parse_qs(body, keep_blank_values=True)

        result: dict[str, str | list[str]] = {}
        for key, values in parsed.items():
            if len(values) == 1:
                result[key] = values[0]
            else:
                result[key] = values

        return result

    async def multipart(
        self,
    # pyrefly: ignore [unknown-name]
    ) -> tuple[Mapping[str, str | list[str]], list["UploadFile"]]:
        """
        Parse a ``multipart/form-data`` body.

        Returns ``(form_fields, files)`` where *files* is a list of
        :class:`~thor.multipart.UploadFile` instances.
        """
        from thor.multipart import UploadFile, parse_multipart

        raw_body = await self.body()
        boundary = self._extract_boundary()
        if boundary is None:
            return {}, []
        return parse_multipart(raw_body, boundary)

    def _extract_boundary(self) -> str | None:
        """Extract the multipart boundary from the Content-Type header."""
        ct = self.content_type
        for part in ct.split(";"):
            part = part.strip()
            if part.lower().startswith("boundary="):
                return part.split("=", 1)[1].strip('"')
        return None

    # pyrefly: ignore [unknown-name]
    async def files(self) -> list["UploadFile"]:
        """Convenience: return only the file uploads from a multipart body."""
        _fields, file_list = await self.multipart()
        return file_list
    
    def get_header(self, name: str, default: str | None = None) -> str | None:
        """Get a specific header value."""
        return self.headers.get(name.lower(), default)
    
    def get_query(self, name: str, default: str | None = None) -> str | None:
        """Get a specific query parameter."""
        value = self.query_params.get(name, default)
        if isinstance(value, list):
            return value[0] if value else default
        return value
    
    def get_cookie(self, name: str, default: str | None = None) -> str | None:
        """Get a specific cookie value."""
        return self.cookies.get(name, default)
