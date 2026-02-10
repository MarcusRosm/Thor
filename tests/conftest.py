"""
Helpers for building ASGI scope / receive / send in tests.
"""

from collections.abc import Callable, Awaitable
from typing import Any


def make_scope(
    method: str = "GET",
    path: str = "/",
    headers: dict[str, str] | None = None,
    query_string: str = "",
    scope_type: str = "http",
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal ASGI scope dict."""
    raw_headers: list[tuple[bytes, bytes]] = []
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))

    scope: dict[str, Any] = {
        "type": scope_type,
        "method": method,
        "path": path,
        "query_string": query_string.encode("utf-8"),
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "scheme": "http",
    }
    if extras:
        scope.update(extras)
    return scope


def make_receive(body: bytes = b"") -> Callable[[], Awaitable[dict[str, Any]]]:
    """Create a simple ASGI receive callable that yields one body chunk."""
    called = False

    async def receive() -> dict[str, Any]:
        nonlocal called
        if not called:
            called = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


class ResponseCapture:
    """Captures ASGI send() messages for assertions."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.status: int = 0
        self.headers: dict[str, str] = {}
        self.body: bytes = b""

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if message["type"] == "http.response.start":
            self.status = message.get("status", 0)
            for name, value in message.get("headers", []):
                self.headers[name.decode("latin-1").lower()] = value.decode("latin-1")
        elif message["type"] == "http.response.body":
            self.body += message.get("body", b"")


# ---------------------------------------------------------------------------
# WebSocket test helpers
# ---------------------------------------------------------------------------


def make_ws_scope(
    path: str = "/ws",
    headers: dict[str, str] | None = None,
    query_string: str = "",
) -> dict[str, Any]:
    """Build a minimal ASGI websocket scope."""
    raw_headers: list[tuple[bytes, bytes]] = []
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
    
    return {
        "type": "websocket",
        "path": path,
        "query_string": query_string.encode("utf-8"),
        "headers": raw_headers,
        "client": ("127.0.0.1", 9999),
        "scheme": "ws",
    }


class WebSocketCapture:
    """Captures messages sent to a WebSocket client."""

    def __init__(self, incoming: list[dict[str, Any]] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._incoming = list(incoming or [])
        self._idx = 0

    async def receive(self) -> dict[str, Any]:
        """Simulate receiving messages from the client."""
        if self._idx < len(self._incoming):
            msg = self._incoming[self._idx]
            self._idx += 1
            return msg
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(self, message: dict[str, Any]) -> None:
        """Capture messages sent to the client."""
        self.sent.append(message)


# ---------------------------------------------------------------------------
# Multipart test helpers
# ---------------------------------------------------------------------------


def build_multipart_body(
    boundary: str,
    parts: list[dict[str, Any]],
) -> bytes:
    """
    Build a multipart/form-data body for testing.

    Args:
        boundary: The multipart boundary string
        parts: List of dicts with keys:
            - name: field name
            - data: field value (str or bytes)
            - filename: (optional) filename for file uploads
            - content_type: (optional) Content-Type for file uploads

    Example:
        body = build_multipart_body("boundary", [
            {"name": "field1", "data": "value1"},
            {"name": "file1", "data": b"content", "filename": "test.txt"},
        ])
    """
    lines: list[bytes] = []

    for part in parts:
        lines.append(f"--{boundary}".encode())

        # Content-Disposition header
        if "filename" in part:
            disposition = f'Content-Disposition: form-data; name="{part["name"]}"; filename="{part["filename"]}"'
        else:
            disposition = f'Content-Disposition: form-data; name="{part["name"]}"'
        lines.append(disposition.encode())

        # Content-Type header (for file uploads)
        if "content_type" in part:
            lines.append(f'Content-Type: {part["content_type"]}'.encode())

        # Empty line before body
        lines.append(b"")

        # Body data
        data = part["data"]
        if isinstance(data, str):
            lines.append(data.encode())
        else:
            lines.append(data)

    # Final boundary
    lines.append(f"--{boundary}--".encode())

    return b"\r\n".join(lines) + b"\r\n"

