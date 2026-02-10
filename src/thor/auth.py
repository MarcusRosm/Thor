"""
Authentication system for Thor framework.
Provides pluggable authentication backends and user management.
"""
import jwt

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from thor.exceptions import Forbidden, Unauthorized
from thor.middleware import Middleware
from thor.request import Request
from thor.types import ASGIApp, Receive, Scope, Send


@dataclass
class User:
    """
    User representation for authentication.
    
    Follows Single Responsibility Principle - represents user identity only.
    """
    
    id: str
    username: str | None = None
    email: str | None = None
    is_authenticated: bool = True
    is_active: bool = True
    scopes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    
    @property
    def identity(self) -> str:
        """Return the user's identity (ID)."""
        return self.id
    
    def has_scope(self, scope: str) -> bool:
        """Check if user has a specific scope/permission."""
        return scope in self.scopes


@dataclass
class AnonymousUser:
    """Anonymous user for unauthenticated requests."""
    
    id: str = ""
    username: str | None = None
    email: str | None = None
    is_authenticated: bool = False
    is_active: bool = False
    scopes: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    
    @property
    def identity(self) -> None:
        """Anonymous users have no identity."""
        return None
    
    def has_scope(self, scope: str) -> bool:
        """Anonymous users have no scopes."""
        return False


class AuthBackend(ABC):
    """
    Abstract authentication backend.
    
    Follows Dependency Inversion Principle - authentication middleware
    depends on this abstraction, not concrete implementations.
    
    Implements the Strategy pattern for pluggable authentication.
    """
    
    @abstractmethod
    async def authenticate(self, request: Request) -> User | AnonymousUser:
        """
        Authenticate a request and return a User or AnonymousUser.
        
        Args:
            request: The incoming request.
            
        Returns:
            User if authenticated, AnonymousUser otherwise.
        """
        ...


class TokenAuthBackend(AuthBackend):
    """
    Token-based authentication backend.
    Expects Authorization header with "Bearer <token>" format.
    """
    
    def __init__(
        self,
        secret_key: str,
        verify_token: Any = None,  # Callable[[str], User | None]
        token_prefix: str = "Bearer",
        algorithm: str = "HS256",
    ) -> None:
        self._secret_key = secret_key
        self._verify_token = verify_token
        self._token_prefix = token_prefix
        self._algorithm = algorithm
    
    async def authenticate(self, request: Request) -> User | AnonymousUser:
        auth_header = request.get_header("authorization")
        
        if not auth_header:
            return AnonymousUser()
        
        try:
            scheme, token = auth_header.split(" ", 1)
        except ValueError:
            return AnonymousUser()
        
        if scheme.lower() != self._token_prefix.lower():
            return AnonymousUser()
        
        if self._verify_token:
            user = await self._verify_token(token)
            if user:
                return user
        
        return AnonymousUser()

    async def verify_token(self, token: str) -> User | None:
        try:
            payload: dict[str, Any] = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return User(
                id=payload["sub"],
                username=payload.get("username"),
            )
        except jwt.ExpiredSignatureError:
            return None  # token expired → AnonymousUser
        except jwt.InvalidTokenError:
            return None  # bad signature, malformed, etc.


class SessionAuthBackend(AuthBackend):
    """
    Session-based authentication backend.
    Retrieves user from session data.
    """
    
    def __init__(
        self,
        session_key: str = "user_id",
        load_user: Any = None,  # Callable[[str], User | None]
    ) -> None:
        self._session_key = session_key
        self._load_user = load_user
    
    async def authenticate(self, request: Request) -> User | AnonymousUser:
        session = request._scope.get("session")
        
        if not session:
            return AnonymousUser()
        
        user_id = session.get(self._session_key)
        if not user_id:
            return AnonymousUser()
        
        if self._load_user:
            user = await self._load_user(user_id)
            if user:
                return user
        
        return AnonymousUser()


class JWTAuthBackend(AuthBackend):
    """JWT-based authentication backend."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        token_prefix: str = "Bearer",
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._token_prefix = token_prefix

    async def authenticate(self, request: Request) -> User | AnonymousUser:
        auth_header: str | None = request.get_header("authorization")
        if not auth_header:
            return AnonymousUser()

        try:
            scheme, token = auth_header.split(" ", 1)
        except ValueError:
            return AnonymousUser()

        if scheme.lower() != self._token_prefix.lower():
            return AnonymousUser()

        try:
            payload: dict[str, Any] = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return User(
                id=payload["sub"],
                username=payload.get("username"),
                scopes=payload.get("scopes", []),
            )
        except jwt.ExpiredSignatureError:
            return AnonymousUser()
        except jwt.InvalidTokenError:
            return AnonymousUser()


class BasicAuthBackend(AuthBackend):
    """
    HTTP Basic authentication backend.
    """
    
    def __init__(
        self,
        verify_credentials: Any = None,  # Callable[[str, str], User | None]
    ) -> None:
        self._verify_credentials = verify_credentials
    
    async def authenticate(self, request: Request) -> User | AnonymousUser:
        import base64
        
        auth_header = request.get_header("authorization")
        
        if not auth_header:
            return AnonymousUser()
        
        try:
            scheme, credentials = auth_header.split(" ", 1)
        except ValueError:
            return AnonymousUser()
        
        if scheme.lower() != "basic":
            return AnonymousUser()
        
        try:
            decoded = base64.b64decode(credentials).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return AnonymousUser()
        
        if self._verify_credentials:
            user = await self._verify_credentials(username, password)
            if user:
                return user
        
        return AnonymousUser()


class AuthMiddleware(Middleware):
    """
    Authentication middleware.
    Attaches user information to each request.
    """
    
    def __init__(
        self,
        app: ASGIApp,
        backend: AuthBackend,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.backend = backend
        self.exclude_paths = exclude_paths or []
    
    async def process(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        
        # Skip authentication for excluded paths
        if any(request.path.startswith(p) for p in self.exclude_paths):
            scope["user"] = AnonymousUser()
            await self.app(scope, receive, send)
            return
        
        # Authenticate request
        user = await self.backend.authenticate(request)
        scope["user"] = user
        
        await self.app(scope, receive, send)


def login_required(handler: Any) -> Any:
    """
    Decorator that requires authentication.
    Raises Unauthorized if user is not authenticated.
    """
    async def wrapper(request: Request, *args: Any, **kwargs: Any) -> Any:
        user = request._scope.get("user")
        
        if not user or not user.is_authenticated:
            raise Unauthorized("Authentication required")
        
        return await handler(request, *args, **kwargs)
    
    wrapper.__name__ = handler.__name__
    wrapper.__doc__ = handler.__doc__
    return wrapper


def require_scopes(*required_scopes: str) -> Any:
    """
    Decorator that requires specific scopes/permissions.
    Raises Forbidden if user lacks required scopes.
    """
    def decorator(handler: Any) -> Any:
        async def wrapper(request: Request, *args: Any, **kwargs: Any) -> Any:
            user = request._scope.get("user")
            
            if not user or not user.is_authenticated:
                raise Unauthorized("Authentication required")
            
            for scope in required_scopes:
                if not user.has_scope(scope):
                    raise Forbidden(f"Missing required scope: {scope}")
            
            return await handler(request, *args, **kwargs)
        
        wrapper.__name__ = handler.__name__
        wrapper.__doc__ = handler.__doc__
        return wrapper
    
    return decorator