"""
Session management for Thor framework.
Provides server-side session storage with secure cookie tokens.
"""

from typing import Optional
import secrets
import time
from abc import ABC, abstractmethod
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import Any, Iterator

from thor.cookies import CookieOptions, SecureCookie, format_set_cookie
from thor.middleware import Middleware
from thor.request import Request
from thor.types import ASGIApp, Receive, Scope, Send


@dataclass
class SessionData:
    """Session data container with metadata."""
    
    data: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    accessed_at: float = field(default_factory=time.time)
    modified: bool = False


class Session(MutableMapping[str, Any]):
    """
    Session interface providing dict-like access to session data.
    
    Follows Interface Segregation Principle - provides a simple
    dict-like interface for session access.
    """
    
    def __init__(self, session_data: SessionData) -> None:
        self._session_data = session_data
    
    def __getitem__(self, key: str) -> Any:
        return self._session_data.data[key]
    
    def __setitem__(self, key: str, value: Any) -> None:
        self._session_data.data[key] = value
        self._session_data.modified = True
    
    def __delitem__(self, key: str) -> None:
        del self._session_data.data[key]
        self._session_data.modified = True
    
    def __iter__(self) -> Iterator[str]:
        return iter(self._session_data.data)
    
    def __len__(self) -> int:
        return len(self._session_data.data)
    
    def __contains__(self, key: object) -> bool:
        return key in self._session_data.data
    
    @property
    def is_new(self) -> bool:
        """Check if this is a new session."""
        return self._session_data.created_at == self._session_data.accessed_at
    
    @property
    def is_modified(self) -> bool:
        """Check if session data has been modified."""
        return self._session_data.modified
    
    def clear(self) -> None:
        """Clear all session data."""
        self._session_data.data.clear()
        self._session_data.modified = True
    
    def flash(self, key: str, value: Any) -> None:
        """Set a flash message (available for one request only)."""
        flash_data = self._session_data.data.get("_flash", {})
        flash_data[key] = value
        self._session_data.data["_flash"] = flash_data
        self._session_data.modified = True
    
    def get_flash(self, key: str, default: Any = None) -> Any:
        """Get and remove a flash message."""
        flash_data = self._session_data.data.get("_flash", {})
        value = flash_data.pop(key, default)
        if not flash_data:
            self._session_data.data.pop("_flash", None)
        else:
            self._session_data.data["_flash"] = flash_data
        self._session_data.modified = True
        return value


class SessionBackend(ABC):
    """
    Abstract session storage backend.
    
    Follows Dependency Inversion Principle - high-level session management
    depends on this abstraction, not concrete implementations.
    """
    
    @abstractmethod
    async def load(self, session_id: str) -> SessionData | None:
        """Load session data for the given session ID."""
        ...
    
    @abstractmethod
    async def save(self, session_id: str, data: SessionData) -> None:
        """Save session data."""
        ...
    
    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete a session."""
        ...
    
    @abstractmethod
    async def cleanup(self, max_age: int) -> None:
        """Clean up expired sessions."""
        ...


class InMemorySessionBackend(SessionBackend):
    """
    In-memory session storage.
    Suitable for development and single-instance deployments.
    
    Warning: Sessions are lost on restart and not shared across workers.
    Use FileSessionBackend or a custom backend for production.
    """
    
    def __init__(self) -> None:
        self._sessions: dict[str, SessionData] = {}
    
    async def load(self, session_id: str) -> SessionData | None:
        data = self._sessions.get(session_id)
        if data:
            data.accessed_at = time.time()
        return data
    
    async def save(self, session_id: str, data: SessionData) -> None:
        self._sessions[session_id] = data
    
    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
    
    async def cleanup(self, max_age: int) -> None:
        current_time = time.time()
        expired = [
            sid for sid, data in self._sessions.items()
            if current_time - data.accessed_at > max_age
        ]
        for sid in expired:
            del self._sessions[sid]


class FileSessionBackend(SessionBackend):
    """
    File-system session storage.

    Each session is stored as a JSON file in a configurable directory.
    Suitable for production single-node or shared-filesystem deployments.
    Sessions survive restarts and are shareable across workers that
    can access the same directory.

    Uses atomic writes (write-to-temp then rename) to prevent
    corruption from concurrent requests.
    """

    def __init__(self, directory: str = ".thor_sessions") -> None:
        import os
        self._directory = os.path.abspath(directory)
        os.makedirs(self._directory, exist_ok=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _path_for(self, session_id: str) -> str:
        import os
        import re
        # Sanitise session_id to prevent directory traversal
        safe_id = re.sub(r"[^a-zA-Z0-9_\-]", "", session_id)
        if not safe_id:
            raise ValueError("Invalid session id")
        return os.path.join(self._directory, f"{safe_id}.json")

    @staticmethod
    def _serialise(data: SessionData) -> str:
        import json
        return json.dumps({
            "data": data.data,
            "created_at": data.created_at,
            "accessed_at": data.accessed_at,
        })

    @staticmethod
    def _deserialise(raw: str) -> SessionData:
        import json
        obj = json.loads(raw)
        return SessionData(
            data=obj["data"],
            created_at=obj["created_at"],
            accessed_at=obj["accessed_at"],
        )

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    async def load(self, session_id: str) -> SessionData | None:
        import os
        path = self._path_for(session_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = self._deserialise(f.read())
            data.accessed_at = time.time()
            # Persist the updated accessed_at
            await self.save(session_id, data)
            return data
        except (OSError, ValueError, KeyError):
            return None

    async def save(self, session_id: str, data: SessionData) -> None:
        import os
        import tempfile
        path = self._path_for(session_id)
        # Atomic write: write to temp file in same dir, then rename
        fd, tmp_path = tempfile.mkstemp(dir=self._directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self._serialise(data))
            os.replace(tmp_path, path)
        except BaseException:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    async def delete(self, session_id: str) -> None:
        import os
        path = self._path_for(session_id)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    async def cleanup(self, max_age: int) -> None:
        import os
        current_time = time.time()
        try:
            entries = os.listdir(self._directory)
        except OSError:
            return
        for filename in entries:
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self._directory, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = self._deserialise(f.read())
                if current_time - data.accessed_at > max_age:
                    os.unlink(path)
            except (OSError, ValueError, KeyError):
                continue


class SessionMiddleware(Middleware):
    """
    Session middleware that manages session lifecycle.
    
    Uses the Strategy pattern for session backend selection.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        cookie_name: str = "thor_session",
        max_age: int = 86400 * 14,  # 14 days
        backend: SessionBackend | None = None,
        cookie_options: CookieOptions | None = None,
    ) -> None:
        super().__init__(app)
        self.secret_key = secret_key
        self.cookie_name = cookie_name
        self.max_age = max_age
        self.backend = backend or InMemorySessionBackend()
        self.cookie_options = cookie_options or CookieOptions(max_age=max_age)
        self._secure_cookie = SecureCookie(secret_key)
    
    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        
        # Load or create session
        session_id = self._get_session_id(request)
        session_data: SessionData | None = None
        
        if session_id:
            session_data = await self.backend.load(session_id)
        
        if session_data is None:
            session_id = self._generate_session_id()
            session_data = SessionData()
        
        session = Session(session_data)
        scope["session"] = session
        
        # Wrap send to set session cookie
        async def send_with_session(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                # Save session if modified
                if session.is_modified:
                    # pyrefly: ignore [bad-argument-type]
                    await self.backend.save(session_id, session_data)
                
                # Set session cookie
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                # pyrefly: ignore [bad-argument-type]
                signed_id: str = self._secure_cookie.sign(session_id)
                cookie: str = format_set_cookie(
                    self.cookie_name,
                    signed_id,
                    self.cookie_options,
                )
                headers.append((b"set-cookie", cookie.encode("latin-1")))
                message["headers"] = headers
            
            await send(message)
        
        # pyrefly: ignore [bad-argument-type]
        await self.app(scope, receive, send_with_session)
    
    def _get_session_id(self, request: Request) -> Optional[str]:
        """Extract and verify session ID from cookie."""
        signed_id: Optional[str] = request.get_cookie(self.cookie_name)
        if not signed_id:
            return None
        
        session_id: Optional[str] = self._secure_cookie.unsign(signed_id, self.max_age)
        return session_id
    
    def _generate_session_id(self) -> str:
        """Generate a new cryptographically secure session ID."""
        return secrets.token_urlsafe(32)
