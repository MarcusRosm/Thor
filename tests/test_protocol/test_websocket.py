"""Tests for thor.websocket — WebSocket class and routing."""

import asyncio
from typing import Any

import pytest

from thor.app import Thor
from thor.websocket import WebSocket, WebSocketDisconnect


def _ws_scope(path: str = "/ws", headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Build a minimal ASGI websocket scope."""
    raw_headers: list[tuple[bytes, bytes]] = []
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
    return {
        "type": "websocket",
        "path": path,
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 9999),
        "scheme": "ws",
    }


class _WSCapture:
    """Captures messages sent to the WebSocket client."""

    def __init__(self, incoming: list[dict[str, Any]] | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self._incoming = list(incoming or [])
        self._idx = 0

    async def receive(self) -> dict[str, Any]:
        if self._idx < len(self._incoming):
            msg = self._incoming[self._idx]
            self._idx += 1
            return msg
        return {"type": "websocket.disconnect", "code": 1000}

    async def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)


class TestWebSocket:
    async def test_accept(self) -> None:
        cap = _WSCapture()
        ws = WebSocket(_ws_scope(), cap.receive, cap.send)
        await ws.accept()
        assert cap.sent[0]["type"] == "websocket.accept"

    async def test_send_text(self) -> None:
        cap = _WSCapture()
        ws = WebSocket(_ws_scope(), cap.receive, cap.send)
        await ws.accept()
        await ws.send_text("hello")
        assert cap.sent[1] == {"type": "websocket.send", "text": "hello"}

    async def test_send_bytes(self) -> None:
        cap = _WSCapture()
        ws = WebSocket(_ws_scope(), cap.receive, cap.send)
        await ws.accept()
        await ws.send_bytes(b"\x00\x01")
        assert cap.sent[1] == {"type": "websocket.send", "bytes": b"\x00\x01"}

    async def test_send_json(self) -> None:
        cap = _WSCapture()
        ws = WebSocket(_ws_scope(), cap.receive, cap.send)
        await ws.accept()
        await ws.send_json({"key": "val"})
        assert '"key"' in cap.sent[1]["text"]

    async def test_receive_text(self) -> None:
        incoming = [{"type": "websocket.receive", "text": "hi"}]
        cap = _WSCapture(incoming)
        ws = WebSocket(_ws_scope(), cap.receive, cap.send)
        text = await ws.receive_text()
        assert text == "hi"

    async def test_receive_disconnect_raises(self) -> None:
        cap = _WSCapture()  # no incoming → immediate disconnect
        ws = WebSocket(_ws_scope(), cap.receive, cap.send)
        with pytest.raises(WebSocketDisconnect):
            await ws.receive_text()

    async def test_close(self) -> None:
        cap = _WSCapture()
        ws = WebSocket(_ws_scope(), cap.receive, cap.send)
        await ws.accept()
        await ws.close(code=1001, reason="going away")
        assert cap.sent[-1]["type"] == "websocket.close"
        assert cap.sent[-1]["code"] == 1001

    async def test_properties(self) -> None:
        ws = WebSocket(
            _ws_scope(path="/chat", headers={"X-Custom": "val"}),
            lambda: asyncio.sleep(0),
            lambda m: asyncio.sleep(0),
        )
        assert ws.path == "/chat"
        assert ws.headers["x-custom"] == "val"
        assert ws.client == ("127.0.0.1", 9999)


class TestWebSocketRouting:
    async def test_app_websocket_decorator(self) -> None:
        app = Thor()

        @app.websocket("/ws/echo")
        async def echo(ws: WebSocket):
            await ws.accept()
            msg = await ws.receive_text()
            await ws.send_text(f"echo: {msg}")
            await ws.close()

        incoming = [{"type": "websocket.receive", "text": "ping"}]
        cap = _WSCapture(incoming)
        scope = _ws_scope(path="/ws/echo")
        await app(scope, cap.receive, cap.send)

        assert cap.sent[0]["type"] == "websocket.accept"
        assert cap.sent[1]["text"] == "echo: ping"
        assert cap.sent[2]["type"] == "websocket.close"

    async def test_unknown_ws_path_closed(self) -> None:
        app = Thor()
        cap = _WSCapture()
        scope = _ws_scope(path="/nonexistent")
        await app(scope, cap.receive, cap.send)
        assert cap.sent[0]["type"] == "websocket.close"
        assert cap.sent[0]["code"] == 1008
