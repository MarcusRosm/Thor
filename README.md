# Thor ⚡

A Python 3.14 micro web framework built on top of uvicorn with modern async/await support.

## Features

- **🚀 ASGI-based**: Built on uvicorn for high performance
- **🔒 Secure Cookies**: HMAC-signed cookies with expiration support
- **📦 Sessions**: Server-side session management with pluggable backends
- **🔐 Authentication**: Flexible auth system with multiple backends (Token, Session, Basic)
- **⏳ Lifespan Management**: Startup/shutdown hooks for database connections, etc.
- **🛣️ Routing**: Path parameters with type conversion, nested routers
- **🔗 Middleware**: Chain of responsibility pattern with CORS, logging, error handling


## Quick Start

```python
from thor import Thor, Request

app = Thor(debug=True)

@app.get("/")
async def hello(request: Request) -> dict:
    return {"message": "Hello, World! ⚡"}

if __name__ == "__main__":
    app.run()
```

## Installation

```bash
# Using uv
uv pip install -e .

# Or with development dependencies
uv pip install -e ".[dev]"
```

## Running the Example

```bash
# Using uvicorn directly
uvicorn main:app --reload

# Or run the main file
python main.py
```

## Core Components

### Routing

```python
from thor import Thor, Request, Router

app = Thor()

# Basic routes
@app.get("/users/{user_id:int}")
async def get_user(request: Request, user_id: int) -> dict:
    return {"user_id": user_id}

# Subrouters
api = Router(prefix="/api/v1")

@api.get("/items")
async def list_items(request: Request) -> dict:
    return {"items": []}

app.include_router(api)
```

### Sessions

```python
from thor import Thor
from thor.session import SessionMiddleware

app = Thor(secret_key="your-secret")
app.add_middleware(SessionMiddleware, secret_key="session-secret")

@app.get("/counter")
async def counter(request: Request) -> dict:
    session = request._scope["session"]
    session["count"] = session.get("count", 0) + 1
    return {"count": session["count"]}
```

### Authentication

```python
from thor import Thor
from thor.auth import AuthMiddleware, TokenAuthBackend, User, login_required

async def verify_token(token: str) -> User | None:
    if token == "valid-token":
        return User(id="1", username="admin")
    return None

app = Thor()
app.add_middleware(
    AuthMiddleware,
    backend=TokenAuthBackend(verify_token=verify_token),
)

@app.get("/protected")
@login_required
async def protected(request: Request) -> dict:
    user = request._scope["user"]
    return {"user": user.username}
```

### JWT Authentication

Thor supports JWT-based authentication via `JWTAuthBackend` using [PyJWT](https://pyjwt.readthedocs.io/). The `/login` route issues a signed token and the middleware verifies it on every request.

```python
import jwt
import time
from thor import Thor, Request, JSONResponse
from thor.auth import AuthMiddleware, JWTAuthBackend, User, login_required

app = Thor(secret_key="your-secret-key")

app.add_middleware(
    AuthMiddleware,
    backend=JWTAuthBackend(secret_key=app.secret_key),
)

@app.post("/login")
async def login(request: Request) -> JSONResponse:
    data = await request.json()
    if data.get("username") == "admin" and data.get("password") == "password":
        payload = {
            "sub": "1",                        # registered claim: subject (user ID)
            "username": data["username"],
            "iat": int(time.time()),            # registered claim: issued at
            "exp": int(time.time()) + 3600,     # registered claim: expiration
        }
        token = jwt.encode(payload, app.secret_key, algorithm="HS256")
        return JSONResponse({"token": token})
    return JSONResponse({"error": "Invalid credentials"}, status_code=401)

@app.get("/protected")
@login_required
async def protected(request: Request) -> dict:
    user = request._scope["user"]
    return {"user": user.username}
```

#### HS256 vs RS256 — Scaling Considerations

Thor defaults to **HS256** (symmetric HMAC). This is the right choice when a single service both issues and verifies tokens.

| | HS256 (symmetric) | RS256 (asymmetric) |
|---|---|---|
| **Keys** | One shared secret key | Private key (sign) + Public key (verify) |
| **Performance** | Fast — HMAC-SHA256 | ~10x slower — RSA operations |
| **Best for** | Single service / monolith | Microservices, third-party consumers |
| **Security model** | Any service with the key can issue & verify | Only the issuer holds the private key; verifiers use the public key and **cannot forge tokens** |

**When to switch to RS256:**

- **Multiple services verify tokens** — distribute the public key to verifiers without giving them the ability to issue tokens
- **Separate auth service** — an identity provider issues JWTs; other services only need the public key
- **Third-party consumers** — external clients verify tokens via a published public key
- **Zero-trust between services** — a compromised verifier cannot forge new tokens

To switch, install `pyjwt[crypto]` (which adds the `cryptography` package) and change the algorithm:

```python
# Signing (login route) — private key
token = jwt.encode(payload, private_key, algorithm="RS256")

# Verifying (JWTAuthBackend) — public key
payload = jwt.decode(token, public_key, algorithms=["RS256"])
```

> **Note:** The `secret_key` parameter in `JWTAuthBackend` holds whichever key is needed for verification — the shared secret for HS256, or the public key for RS256.

### Lifespan Events

```python
from thor import Thor

app = Thor()

@app.on_startup
async def startup():
    app.state["db"] = await create_database_pool()

@app.on_shutdown
async def shutdown():
    await app.state["db"].close()
```

### Middleware

```python
from thor import Thor
from thor.middleware import CORSMiddleware, RequestLoggingMiddleware

app = Thor()

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com"],
    allow_methods=["GET", "POST"],
)
```

### Responses

```python
from thor import JSONResponse, HTMLResponse, RedirectResponse
from thor.response import StreamingResponse, FileResponse

@app.get("/json")
async def json_response(request: Request):
    return JSONResponse({"data": "value"}, status_code=200)

@app.get("/html")
async def html_response(request: Request):
    return HTMLResponse("<h1>Hello</h1>")

@app.get("/redirect")
async def redirect(request: Request):
    return RedirectResponse("/new-location")
```

## Testing

### Running the tests

```bash
uv run pytest tests/ -v
```

`uv run` executes within the project's virtual environment and `pytest` discovers and runs the 98 tests across 9 test files.

### How it works

The test configuration in `pyproject.toml` is:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`asyncio_mode = "auto"` tells **pytest-asyncio** to automatically treat every `async def test_*` method as an asyncio coroutine with a fresh event loop per test, eliminating the need for `@pytest.mark.asyncio` decorators.

The tests **never start uvicorn**. Since Thor is an ASGI framework, the entire request/response lifecycle is just Python callables with the signature `async (scope, receive, send)`. Three helpers in `tests/conftest.py` simulate the ASGI protocol in-process:

- **`make_scope()`** — builds the `scope` dict (method, path, headers, query string, etc.) that an ASGI server would normally construct from a raw HTTP connection.
- **`make_receive(body)`** — returns an async callable that mimics the ASGI `receive` channel, yielding a single request body chunk.
- **`ResponseCapture`** — an async callable that acts as the ASGI `send` channel, collecting status code, headers, and body bytes for assertions.

A typical test looks like:

```python
scope = make_scope(method="GET", path="/data")   # fake ASGI scope
cap = ResponseCapture()                           # fake send channel
await app(scope, make_receive(b""), cap)           # call the app directly
assert cap.status == 200                           # inspect what was "sent"
```

No socket, no HTTP parsing, no server process — just direct ASGI callable invocation.

## Project Structure

```
thor/
├── src/
│   └── thor/
│       ├── __init__.py    # Package exports
│       ├── app.py         # Main Thor application
│       ├── auth.py        # Authentication system
│       ├── cookies.py     # Secure cookie handling
│       ├── exceptions.py  # HTTP and framework exceptions
│       ├── lifespan.py    # Startup/shutdown management
│       ├── middleware.py  # Middleware system
│       ├── request.py     # Request wrapper
│       ├── response.py    # Response types
│       ├── routing.py     # URL routing
│       ├── session.py     # Session management
│       └── types.py       # Type definitions
├── main.py                # Example application
├── pyproject.toml
└── README.md
```


---

## Architecture Diagrams

### Class Diagram - Core Components

```mermaid
classDiagram
    class Thor {
        +debug: bool
        +title: str
        +version: str
        +state: LifespanState
        -_router: Router
        -_lifespan: Lifespan
        -_middleware_stack: MiddlewareStack
        +__call__(scope, receive, send)
        +add_route(path, handler, methods)
        +add_middleware(middleware_class)
        +include_router(router, prefix)
        +on_startup(handler)
        +on_shutdown(handler)
        +get(path) decorator
        +post(path) decorator
        +run(host, port)
    }

    class Router {
        -_prefix: str
        -_routes: List~Route~
        -_subrouters: List~Router~
        +add_route(path, handler, methods)
        +include_router(router, prefix)
        +match(path, method): Route, params
        +get(path) decorator
        +post(path) decorator
    }

    class Route {
        +path: str
        +handler: RouteHandler
        +methods: Set~str~
        +name: str
        -_pattern: Pattern
        -_param_types: Dict
        +match(path): Dict~params~
    }

    class Request {
        -_scope: Scope
        -_receive: Receive
        -_body: bytes
        +state: Dict
        +method: str
        +path: str
        +headers: Mapping
        +cookies: Mapping
        +query_params: Mapping
        +body() bytes
        +json() Any
        +form() Mapping
    }

    class Response {
        <<abstract>>
        +status_code: int
        +media_type: str
        -_headers: Dict
        -_cookies: List
        +render()* bytes
        +set_header(name, value)
        +set_cookie(name, value, options)
        +__call__(send)
    }

    class JSONResponse {
        +media_type: "application/json"
        +render(): bytes
    }

    class HTMLResponse {
        +media_type: "text/html"
        +render(): bytes
    }

    class RedirectResponse {
        +render(): bytes
    }

    Thor "1" *-- "1" Router : contains
    Thor "1" *-- "1" MiddlewareStack : contains
    Thor "1" *-- "1" Lifespan : contains
    Router "1" *-- "*" Route : contains
    Response <|-- JSONResponse
    Response <|-- HTMLResponse
    Response <|-- RedirectResponse
```

### Class Diagram - Middleware System

```mermaid
classDiagram
    class Middleware {
        <<abstract>>
        +app: ASGIApp
        +__call__(scope, receive, send)
        +process(scope, receive, send)*
    }

    class MiddlewareStack {
        -_app: ASGIApp
        -_middleware: List
        -_middleware_options: List
        +add(middleware_class, options)
        +build(): ASGIApp
    }

    class ErrorHandlerMiddleware {
        +debug: bool
        +process(scope, receive, send)
    }

    class CORSMiddleware {
        +allow_origins: List
        +allow_methods: List
        +allow_headers: List
        +allow_credentials: bool
        +process(scope, receive, send)
    }

    class RequestLoggingMiddleware {
        +logger: Logger
        +process(scope, receive, send)
    }

    class SessionMiddleware {
        +secret_key: str
        +cookie_name: str
        +max_age: int
        +backend: SessionBackend
        +process(scope, receive, send)
    }

    class AuthMiddleware {
        +backend: AuthBackend
        +exclude_paths: List
        +process(scope, receive, send)
    }

    Middleware <|-- ErrorHandlerMiddleware
    Middleware <|-- CORSMiddleware
    Middleware <|-- RequestLoggingMiddleware
    Middleware <|-- SessionMiddleware
    Middleware <|-- AuthMiddleware
    MiddlewareStack o-- Middleware : manages
```

### Class Diagram - Session & Authentication

```mermaid
classDiagram
    class SessionBackend {
        <<abstract>>
        +load(session_id)* SessionData
        +save(session_id, data)*
        +delete(session_id)*
        +cleanup(max_age)*
    }

    class InMemorySessionBackend {
        -_sessions: Dict
        +load(session_id): SessionData
        +save(session_id, data)
        +delete(session_id)
        +cleanup(max_age)
    }

    class Session {
        -_session_data: SessionData
        +is_new: bool
        +is_modified: bool
        +__getitem__(key)
        +__setitem__(key, value)
        +flash(key, value)
        +get_flash(key)
        +clear()
    }

    class SessionData {
        +data: Dict
        +created_at: float
        +accessed_at: float
        +modified: bool
    }

    class AuthBackend {
        <<abstract>>
        +authenticate(request)* User
    }

    class TokenAuthBackend {
        -_verify_token: Callable
        -_token_prefix: str
        +authenticate(request): User
    }

    class SessionAuthBackend {
        -_session_key: str
        -_load_user: Callable
        +authenticate(request): User
    }

    class BasicAuthBackend {
        -_verify_credentials: Callable
        +authenticate(request): User
    }

    class User {
        +id: str
        +username: str
        +email: str
        +is_authenticated: bool
        +is_active: bool
        +scopes: List
        +has_scope(scope): bool
    }

    class AnonymousUser {
        +is_authenticated: bool = False
        +identity: None
    }

    SessionBackend <|-- InMemorySessionBackend
    Session "1" --> "1" SessionData : wraps
    AuthBackend <|-- TokenAuthBackend
    AuthBackend <|-- SessionAuthBackend
    AuthBackend <|-- BasicAuthBackend
    AuthBackend ..> User : returns
    AuthBackend ..> AnonymousUser : returns
```

### Class Diagram - Lifespan Management

```mermaid
classDiagram
    class Lifespan {
        -_startup_handlers: List
        -_shutdown_handlers: List
        -_context_manager: Callable
        +state: LifespanState
        +on_startup(handler) decorator
        +on_shutdown(handler) decorator
        +context(cm) decorator
        +startup()
        +shutdown()
        +__call__(state)
    }

    class LifespanState {
        -_data: Dict
        +__getitem__(key)
        +__setitem__(key, value)
        +get(key, default)
        +set(key, value)
        +clear()
    }

    class LifespanProtocolHandler {
        -_app: ASGIApp
        -_lifespan: Lifespan
        +state: LifespanState
        +__call__(scope, receive, send)
        -_handle_lifespan(scope, receive, send)
    }

    Lifespan "1" *-- "1" LifespanState : contains
    LifespanProtocolHandler "1" --> "1" Lifespan : uses
    LifespanProtocolHandler "1" --> "1" LifespanState : exposes
```

### Sequence Diagram - HTTP Request Flow

```mermaid
sequenceDiagram
    participant Client
    participant Uvicorn
    participant Thor
    participant MiddlewareStack
    participant ErrorHandler
    participant CORS
    participant Session
    participant Router
    participant Handler
    participant Response

    Client->>Uvicorn: HTTP Request
    Uvicorn->>Thor: __call__(scope, receive, send)
    Thor->>MiddlewareStack: Forward request
    
    Note over MiddlewareStack: Middleware chain (outer to inner)
    
    MiddlewareStack->>ErrorHandler: process()
    ErrorHandler->>CORS: process()
    CORS->>Session: process()
    
    Session->>Session: Load/Create session
    Session->>Router: _handle_request()
    
    Router->>Router: match(path, method)
    Router->>Handler: await handler(request, **params)
    Handler-->>Router: dict/Response
    
    Router->>Response: Convert to Response if needed
    Response-->>Session: Return response
    
    Session->>Session: Save session if modified
    Session->>Session: Set session cookie
    Session-->>CORS: Response with session
    
    CORS->>CORS: Add CORS headers
    CORS-->>ErrorHandler: Response with CORS
    
    ErrorHandler-->>MiddlewareStack: Final response
    MiddlewareStack-->>Thor: Response
    Thor-->>Uvicorn: ASGI send()
    Uvicorn-->>Client: HTTP Response
```

### Sequence Diagram - Application Startup (Lifespan)

```mermaid
sequenceDiagram
    participant Uvicorn
    participant Thor
    participant LifespanProtocolHandler
    participant Lifespan
    participant StartupHandlers
    participant App State

    Uvicorn->>Thor: __call__(scope={type: "lifespan"})
    Thor->>LifespanProtocolHandler: __call__(scope, receive, send)
    
    LifespanProtocolHandler->>Uvicorn: receive()
    Uvicorn-->>LifespanProtocolHandler: {type: "lifespan.startup"}
    
    LifespanProtocolHandler->>Lifespan: __call__(state)
    
    loop For each startup handler
        Lifespan->>StartupHandlers: await handler()
        StartupHandlers->>App State: Initialize resources
        Note over App State: e.g., DB connection pool
    end
    
    LifespanProtocolHandler->>Uvicorn: send({type: "lifespan.startup.complete"})
    
    Note over Uvicorn,App State: Application is now running...
    
    LifespanProtocolHandler->>Uvicorn: receive()
    Uvicorn-->>LifespanProtocolHandler: {type: "lifespan.shutdown"}
    
    loop For each shutdown handler (reverse order)
        Lifespan->>StartupHandlers: await handler()
        StartupHandlers->>App State: Cleanup resources
        Note over App State: e.g., Close DB connections
    end
    
    LifespanProtocolHandler->>Uvicorn: send({type: "lifespan.shutdown.complete"})
```

### Sequence Diagram - Session Flow

```mermaid
sequenceDiagram
    participant Request
    participant SessionMiddleware
    participant SecureCookie
    participant SessionBackend
    participant Session
    participant Handler

    Request->>SessionMiddleware: Incoming request
    SessionMiddleware->>Request: Get session cookie
    
    alt Cookie exists
        SessionMiddleware->>SecureCookie: unsign(cookie_value)
        SecureCookie-->>SessionMiddleware: session_id
        SessionMiddleware->>SessionBackend: load(session_id)
        SessionBackend-->>SessionMiddleware: SessionData
    else No cookie
        SessionMiddleware->>SessionMiddleware: Generate new session_id
        SessionMiddleware->>SessionMiddleware: Create empty SessionData
    end
    
    SessionMiddleware->>Session: Create Session wrapper
    SessionMiddleware->>Request: Attach session to scope
    
    SessionMiddleware->>Handler: Continue to handler
    Handler->>Session: session["key"] = value
    Session->>Session: Mark as modified
    Handler-->>SessionMiddleware: Response
    
    alt Session modified
        SessionMiddleware->>SessionBackend: save(session_id, data)
    end
    
    SessionMiddleware->>SecureCookie: sign(session_id)
    SecureCookie-->>SessionMiddleware: signed_cookie
    SessionMiddleware->>Response: Set-Cookie header
    SessionMiddleware-->>Request: Response with cookie
```

### Sequence Diagram - Authentication Flow

```mermaid
sequenceDiagram
    participant Client
    participant AuthMiddleware
    participant AuthBackend
    participant Handler
    participant login_required

    Client->>AuthMiddleware: Request with Authorization header
    
    AuthMiddleware->>AuthMiddleware: Check if path excluded
    
    alt Path excluded
        AuthMiddleware->>Handler: Continue (no auth)
    else Path requires auth check
        AuthMiddleware->>AuthBackend: authenticate(request)
        
        alt Token/Session Auth Backend
            AuthBackend->>AuthBackend: Extract token from header
            AuthBackend->>AuthBackend: Verify token
            
            alt Valid token
                AuthBackend-->>AuthMiddleware: User object
            else Invalid token
                AuthBackend-->>AuthMiddleware: AnonymousUser
            end
        end
        
        AuthMiddleware->>AuthMiddleware: Attach user to scope
        AuthMiddleware->>Handler: Continue to handler
    end
    
    Handler->>login_required: @login_required decorator
    
    alt User is authenticated
        login_required->>Handler: Execute handler
        Handler-->>Client: Success response
    else User not authenticated
        login_required-->>Client: 401 Unauthorized
    end
```

### Sequence Diagram - Routing & Path Parameters

```mermaid
sequenceDiagram
    participant Request
    participant Thor
    participant Router
    participant Route
    participant Handler

    Request->>Thor: GET /users/123
    Thor->>Router: match("/users/123", "GET")
    
    loop For each registered route
        Router->>Route: match("/users/123")
        Route->>Route: Apply regex pattern
        Note over Route: Pattern: ^/users/(?P<user_id>\d+)$
        
        alt Pattern matches
            Route->>Route: Extract path params
            Route->>Route: Convert types (int, uuid, etc.)
            Route-->>Router: {"user_id": 123}
        else No match
            Route-->>Router: None
        end
    end
    
    alt Route found & method allowed
        Router-->>Thor: (Route, {"user_id": 123})
        Thor->>Thor: Add path_params to scope
        Thor->>Handler: await handler(request, user_id=123)
        Handler-->>Thor: {"user_id": 123, "name": "John"}
        Thor->>Thor: Convert dict to JSONResponse
        Thor-->>Request: JSON Response
    else No route found
        Router-->>Thor: NotFound exception
        Thor-->>Request: 404 Response
    else Method not allowed
        Router-->>Thor: MethodNotAllowed exception
        Thor-->>Request: 405 Response
    end
```

### Component Interaction Overview

```mermaid
flowchart TB
    subgraph Client
        Browser[Browser/Client]
    end
    
    subgraph ASGI["ASGI Server 'Uvicorn'"]
        UV[Uvicorn]
    end
    
    subgraph Thor["Thor Framework"]
        subgraph Middleware["Middleware Stack"]
            direction TB
            ERR[ErrorHandlerMiddleware]
            CORS[CORSMiddleware]
            LOG[RequestLoggingMiddleware]
            SESS[SessionMiddleware]
            AUTH[AuthMiddleware]
        end
        
        subgraph Core["Core Components"]
            APP[Thor App]
            RTR[Router]
            REQ[Request]
            RES[Response]
        end
        
        subgraph Lifespan["Lifespan Management"]
            LS[Lifespan]
            STATE[App State]
        end
        
        subgraph Security["Security"]
            COOK[SecureCookie]
            SESSB[SessionBackend]
            AUTHB[AuthBackend]
        end
    end
    
    subgraph Handlers["Route Handlers"]
        H1[GET /]
        H2[POST /users]
        H3[GET /users/id]
    end
    
    Browser <-->|HTTP| UV
    UV <-->|ASGI| APP
    
    APP --> Middleware
    ERR --> CORS --> LOG --> SESS --> AUTH
    
    AUTH --> RTR
    RTR --> REQ
    RTR --> H1 & H2 & H3
    H1 & H2 & H3 --> RES
    
    SESS <--> COOK
    SESS <--> SESSB
    AUTH <--> AUTHB
    
    APP <--> LS
    LS <--> STATE
    
    style Thor fill:#e1f5fe
    style Middleware fill:#fff3e0
    style Core fill:#e8f5e9
    style Security fill:#fce4ec
    style Lifespan fill:#f3e5f5
```

