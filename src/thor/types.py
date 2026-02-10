"""
Type definitions for the Thor framework.
Following Python 3.14 typing conventions.
"""

from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any, Protocol, TypeAlias

# ASGI Types
Scope: TypeAlias = MutableMapping[str, Any]
Message: TypeAlias = MutableMapping[str, Any]
Receive: TypeAlias = Callable[[], Awaitable[Message]]
Send: TypeAlias = Callable[[Message], Awaitable[None]]
ASGIApp: TypeAlias = Callable[[Scope, Receive, Send], Awaitable[None]]

# Handler Types
RouteHandler: TypeAlias = Callable[..., Awaitable[Any]]
MiddlewareHandler: TypeAlias = Callable[[ASGIApp], ASGIApp]
LifespanHandler: TypeAlias = Callable[[], Awaitable[None]]

# State Types
State: TypeAlias = MutableMapping[str, Any]
Headers: TypeAlias = Mapping[str, str]
QueryParams: TypeAlias = Mapping[str, str | list[str]]
FormData: TypeAlias = Mapping[str, str | list[str]]
JSONData: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None


class HasState(Protocol):
    """Protocol for objects that have a state attribute."""
    
    state: State


class Authenticatable(Protocol):
    """Protocol for objects that can be authenticated."""
    
    @property
    def is_authenticated(self) -> bool: ...
    
    @property
    def identity(self) -> str | None: ...
