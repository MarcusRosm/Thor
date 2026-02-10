"""
WebSocket support for Thor framework.

Provides a high-level :class:`WebSocket` wrapper around the raw ASGI
WebSocket protocol, plus a :class:`WebSocketRoute` dataclass for
registration via the router.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Awaitable
from dataclasses import dataclass
from typing import Any

from thor.types import Receive, Scope, Send

# Type alias for a websocket handler
WebSocketHandler = Callable[["WebSocket"], Awaitable[None]]


class WebSocketDisconnect(Exception):
    """Raised when a WebSocket client disconnects."""

    def __init__(self, code: int = 1000) -> None:
        self.code = code
        super().__init__(f"WebSocket disconnected with code {code}")


class WebSocket:
    """
    High-level WebSocket interface.

    Wraps the ASGI ``websocket`` scope / receive / send callables
    and exposes a clean async API for accepting, sending, and
    receiving messages.

    Usage inside a handler::

        async def chat(ws: WebSocket):
            await ws.accept()
            while True:
                data = await ws.receive_text()
                await ws.send_text(f"echo: {data}")
    """

    def __init__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self._scope = scope
        self._receive = receive
        self._send = send

    # ------------------------------------------------------------------
    # Scope accessors
    # ------------------------------------------------------------------

    @property
    def path(self) -> str:
        return self._scope.get("path", "/")

    @property
    def query_string(self) -> str:
        return self._scope.get("query_string", b"").decode("utf-8")

    @property
    def headers(self) -> dict[str, str]:
        hdrs: dict[str, str] = {}
        for name, value in self._scope.get("headers", []):
            hdrs[name.decode("latin-1").lower()] = value.decode("latin-1")
        return hdrs

    @property
    def client(self) -> tuple[str, int] | None:
        c = self._scope.get("client")
        return (c[0], c[1]) if c else None

    @property
    def path_params(self) -> dict[str, str]:
        return self._scope.get("path_params", {})

    @property
    def app(self) -> Any:
        return self._scope.get("app")

    # ------------------------------------------------------------------
    # Protocol actions
    # ------------------------------------------------------------------

    async def accept(
        self,
        subprotocol: str | None = None,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        """Accept the incoming WebSocket connection."""
        msg: dict[str, Any] = {"type": "websocket.accept"}
        if subprotocol:
            msg["subprotocol"] = subprotocol
        if headers:
            msg["headers"] = headers
        await self._send(msg)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Close the WebSocket connection."""
        await self._send({
            "type": "websocket.close",
            "code": code,
            "reason": reason,
        })

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send_text(self, data: str) -> None:
        await self._send({"type": "websocket.send", "text": data})

    async def send_bytes(self, data: bytes) -> None:
        await self._send({"type": "websocket.send", "bytes": data})

    async def send_json(self, data: Any, mode: str = "text") -> None:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if mode == "text":
            await self.send_text(encoded)
        else:
            await self.send_bytes(encoded.encode("utf-8"))

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    async def receive(self) -> dict[str, Any]:
        """
        Receive the next WebSocket message.

        Returns the raw ASGI message dict.
        Raises :class:`WebSocketDisconnect` on ``websocket.disconnect``.
        """
        message = await self._receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        # pyrefly: ignore [bad-return]
        return message

    async def receive_text(self) -> str:
        message = await self.receive()
        return message.get("text", "")

    async def receive_bytes(self) -> bytes:
        message = await self.receive()
        return message.get("bytes", b"")

    async def receive_json(self) -> Any:
        text = await self.receive_text()
        return json.loads(text)


# -----------------------------------------------------------------------
# Route dataclass for WebSocket endpoints
# -----------------------------------------------------------------------


@dataclass(slots=True)
class WebSocketRoute:
    """Registration record for a WebSocket endpoint."""

    path: str
    handler: WebSocketHandler
    name: str | None = None
