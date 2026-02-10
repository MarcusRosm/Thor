"""
Response handling for Thor framework.
Implements various response types following Open/Closed Principle.
"""

import json
from abc import ABC, abstractmethod
from typing import Any

from thor.cookies import CookieOptions, format_set_cookie
from thor.types import Send


class Response(ABC):
    """
    Abstract base response class.
    
    Follows Open/Closed Principle - open for extension, closed for modification.
    New response types can be added by extending this class.
    """
    
    media_type: str = "text/plain"
    charset: str = "utf-8"
    
    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._headers: dict[str, str] = headers or {}
        self._cookies: list[str] = []
        self._content = content
    
    @property
    def content_type(self) -> str:
        """Full content type with charset."""
        if self.media_type.startswith("text/") or "json" in self.media_type:
            return f"{self.media_type}; charset={self.charset}"
        return self.media_type
    
    @abstractmethod
    def render(self) -> bytes:
        """Render the response body. Must be implemented by subclasses."""
        ...
    
    def set_header(self, name: str, value: str) -> "Response":
        """Set a response header. Returns self for chaining."""
        self._headers[name] = value
        return self
    
    def set_cookie(
        self,
        name: str,
        value: str,
        options: CookieOptions | None = None,
    ) -> "Response":
        """Set a cookie. Returns self for chaining."""
        cookie = format_set_cookie(name, value, options)
        self._cookies.append(cookie)
        return self
    
    def delete_cookie(
        self,
        name: str,
        path: str = "/",
        domain: str | None = None,
    ) -> "Response":
        """Delete a cookie by setting it to expire. Returns self for chaining."""
        options = CookieOptions(
            max_age=0,
            path=path,
            domain=domain,
            expires="Thu, 01 Jan 1970 00:00:00 GMT",
        )
        return self.set_cookie(name, "", options)
    
    def _build_headers(self) -> list[tuple[bytes, bytes]]:
        """Build header list for ASGI response."""
        headers: list[tuple[bytes, bytes]] = []
        
        # Add content-type
        headers.append((b"content-type", self.content_type.encode("latin-1")))
        
        # Add custom headers
        for name, value in self._headers.items():
            headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
        
        # Add cookies
        for cookie in self._cookies:
            headers.append((b"set-cookie", cookie.encode("latin-1")))
        
        return headers
    
    async def __call__(self, send: Send) -> None:
        """Send the response via ASGI."""
        body = self.render()
        
        await send({
            "type": "http.response.start",
            "status": self.status_code,
            "headers": self._build_headers(),
        })
        
        await send({
            "type": "http.response.body",
            "body": body,
        })


class TextResponse(Response):
    """Plain text response."""
    
    media_type = "text/plain"
    
    def render(self) -> bytes:
        if self._content is None:
            return b""
        if isinstance(self._content, bytes):
            return self._content
        return str(self._content).encode(self.charset)


class HTMLResponse(Response):
    """HTML response."""
    
    media_type = "text/html"
    
    def render(self) -> bytes:
        if self._content is None:
            return b""
        if isinstance(self._content, bytes):
            return self._content
        return str(self._content).encode(self.charset)


class JSONResponse(Response):
    """JSON response with automatic serialization."""
    
    media_type = "application/json"
    
    def __init__(
        self,
        content: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        indent: int | None = None,
    ) -> None:
        super().__init__(content, status_code, headers)
        self._indent = indent
    
    def render(self) -> bytes:
        if self._content is None:
            return b"null"
        return json.dumps(
            self._content,
            ensure_ascii=False,
            allow_nan=False,
            indent=self._indent,
            separators=(",", ":") if self._indent is None else None,
        ).encode(self.charset)


class RedirectResponse(Response):
    """HTTP redirect response."""
    
    def __init__(
        self,
        url: str,
        status_code: int = 307,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(None, status_code, headers)
        self._headers["location"] = url
    
    def render(self) -> bytes:
        return b""


class StreamingResponse(Response):
    """Response for streaming content."""
    
    media_type = "application/octet-stream"
    
    def __init__(
        self,
        content_iterator: Any,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str | None = None,
    ) -> None:
        super().__init__(None, status_code, headers)
        self._iterator = content_iterator
        if media_type:
            self.media_type = media_type
    
    def render(self) -> bytes:
        # Not used for streaming
        return b""
    
    async def __call__(self, send: Send) -> None:
        """Send the streaming response via ASGI."""
        await send({
            "type": "http.response.start",
            "status": self.status_code,
            "headers": self._build_headers(),
        })
        
        async for chunk in self._iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode(self.charset)
            await send({
                "type": "http.response.body",
                "body": chunk,
                "more_body": True,
            })
        
        await send({
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        })


class FileResponse(Response):
    """
    Response for serving files.
    
    Streams file contents in chunks to avoid loading entire files
    into memory. Validates the resolved path against a base directory
    to prevent directory traversal attacks.
    """
    
    # Default chunk size: 64 KB
    CHUNK_SIZE: int = 65_536
    
    def __init__(
        self,
        path: str,
        filename: str | None = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        media_type: str = "application/octet-stream",
        base_directory: str | None = None,
        chunk_size: int = CHUNK_SIZE,
    ) -> None:
        import os
        
        super().__init__(None, status_code, headers)
        
        # Resolve to an absolute, symlink-free path
        resolved = os.path.realpath(path)
        
        # Directory traversal protection
        if base_directory is not None:
            resolved_base = os.path.realpath(base_directory)
            if not resolved.startswith(resolved_base + os.sep) and resolved != resolved_base:
                raise ValueError(
                    f"Path '{path}' resolves outside the allowed base directory"
                )
        
        if not os.path.isfile(resolved):
            raise FileNotFoundError(f"File not found: {path}")
        
        self._path = resolved
        self._filename = filename
        self._chunk_size = chunk_size
        self.media_type = media_type
        
        # Set Content-Length from file size
        stat = os.stat(resolved)
        self._headers["content-length"] = str(stat.st_size)
        
        if filename:
            self._headers["content-disposition"] = f'attachment; filename="{filename}"'
    
    def render(self) -> bytes:
        # Not used — streaming is handled by __call__
        return b""
    
    async def __call__(self, send: Send) -> None:
        """Stream the file via ASGI in chunks."""
        await send({
            "type": "http.response.start",
            "status": self.status_code,
            "headers": self._build_headers(),
        })
        
        with open(self._path, "rb") as f:
            while True:
                chunk = f.read(self._chunk_size)
                if not chunk:
                    break
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                })
        
        await send({
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        })
