"""
Thor Framework - Hello World sample

This demonstrates the basic usage of the Thor micro web framework.
Run with: uv run uvicorn sample:app --reload
"""


import logging
import jwt
import time

from thor import Thor, Request, JSONResponse, Router
from thor.middleware import CORSMiddleware, RequestLoggingMiddleware
from thor.auth import AuthMiddleware, JWTAuthBackend, User, login_required
from thor.session import SessionMiddleware
from thor.cookies import SecureCookie

# =============================================================================
# Application Setup
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("Thor.app")

app: Thor = Thor(
    debug=True,
    title="Thor Demo API",
    version="0.1.0",
    secret_key="{YOUR_SECRET_HERE}",
)


# Add middleware (order matters - first added is outermost)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key="{YOUR_SESSION_SECRET_HERE}",
)
app.add_middleware(
    AuthMiddleware,
    backend=JWTAuthBackend(secret_key=app.secret_key),
)

# =============================================================================
# Lifespan Events (Database initialization example)
# =============================================================================


@app.on_startup
async def startup() -> None:
    """Initialize resources on application startup."""
    logger.info("Thor is starting up...")
    # Example: Initialize database connection
    # app.state["db"] = await create_database_pool()
    app.state["db"] = {"connected": True}  # Placeholder
    logger.info("Database connected")


@app.on_shutdown
async def shutdown() -> None:
    """Cleanup resources on application shutdown."""
    logger.info("Thor is shutting down...")
    # Example: Close database connection
    # await app.state["db"].close()
    app.state["db"] = None
    logger.info("Database disconnected")


# =============================================================================
# Routes - Hello World
# =============================================================================


@app.post("/login")
async def login(request: Request) -> JSONResponse:
    data: dict[str, str] = await request.json()
    username: str = data.get("username", "")
    password: str = data.get("password", "")

    # In a real application, you would verify credentials against a database and hash passwords
    # Or OAuth2 provider, LDAP, etc. This is just a demonstration.
    if username == "admin" and password == "password":
        payload: dict[str, int | str | list[str]] = {
            "sub": "1",                           # user ID or subject, attribute based on registered JWT claims
            "username": username,
            "scopes": ["read"],                   # custom claim for user permissions
            "iat": int(time.time()),              # issued at (registered JWT claims)
            "exp": int(time.time()) + 3600,       # expires in 1 hour (registered JWT claims)
        }
        token: str = jwt.encode(payload, app.secret_key, algorithm="HS256")
        return JSONResponse({"token": token})

    return JSONResponse({"error": "Invalid credentials"}, status_code=401)


@app.get("/protected")
@login_required
async def protected(request: Request) -> dict:
    user = request._scope["user"]
    return {"user": user.username}


@app.get("/")
async def hello_world(request: Request) -> dict:
    """
    Hello World endpoint.

    Returns a JSON greeting message.
    """
    return {
        "message": "Hello, World! Welcome to Thor ⚡",
        "framework": "Thor",
        "version": app.version,
    }


@app.get("/health")
async def health_check(request: Request) -> dict:
    """Health check endpoint."""
    db_status = app.state.get("db", {})
    return {
        "status": "healthy",
        "database": "connected" if db_status.get("connected") else "disconnected",
    }


# =============================================================================
# Routes - Path Parameters
# =============================================================================


@app.get("/users/{user_id:int}")
async def get_user(request: Request, user_id: int) -> dict:
    """
    Get user by ID.

    Demonstrates path parameter extraction with type conversion.
    """
    return {
        "user_id": user_id,
        "username": f"user_{user_id}",
        "email": f"user{user_id}@example.com",
    }


@app.get("/items/{item_id:uuid}")
async def get_item(request: Request, item_id: str) -> dict:
    """Get item by UUID."""
    return {"item_id": item_id, "name": "Sample Item"}


# =============================================================================
# Routes - Request Body & Query Parameters
# =============================================================================


@app.post("/users")
async def create_user(request: Request) -> JSONResponse:
    """
    Create a new user.

    Demonstrates JSON body parsing.
    """
    data = await request.json()

    # In a real app, you would validate and save to database
    return JSONResponse(
        content={
            "message": "User created successfully",
            "user": data,
        },
        status_code=201,
    )


@app.get("/search")
async def search(request: Request) -> dict:
    """
    Search endpoint.

    Demonstrates query parameter handling.
    """
    query = request.get_query("q", "")
    page = int(request.get_query("page", "1") or "1")
    limit = int(request.get_query("limit", "10") or "10")

    return {
        "query": query,
        "page": page,
        "limit": limit,
        "results": [],
    }


# =============================================================================
# Routes - Sessions & Cookies
# =============================================================================


@app.get("/session")
async def get_session(request: Request) -> dict:
    """
    Get current session data.

    Demonstrates session handling.
    """
    session = request._scope.get("session", {})
    return {
        "session_data": dict(session),
        "visit_count": session.get("visits", 0),
    }


@app.post("/session")
async def update_session(request: Request) -> dict:
    """
    Update session data.

    Demonstrates session modification.
    """
    session = request._scope.get("session", {})
    data = await request.json()

    # Update session with provided data
    for key, value in data.items():
        session[key] = value

    # Track visits
    session["visits"] = session.get("visits", 0) + 1

    return {
        "message": "Session updated",
        "session_data": dict(session),
    }


@app.get("/cookie-demo")
async def cookie_demo(request: Request) -> JSONResponse:
    """
    Cookie demonstration.

    Sets a secure cookie in the response.
    """
    from thor.cookies import CookieOptions

    response = JSONResponse(
        {
            "message": "Cookie set!",
            "cookies_received": dict(request.cookies),
        }
    )

    # Set a secure cookie
    response.set_cookie(
        "demo_cookie",
        "hello_thor",
        CookieOptions(
            max_age=3600,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax",
        ),
    )

    return response


# =============================================================================
# Routes - Error Handling
# =============================================================================


@app.get("/error")
async def trigger_error(request: Request) -> dict:
    """Demonstrates error handling."""
    from thor.exceptions import BadRequest

    raise BadRequest("This is a demonstration error")


# =============================================================================
# Subrouter Example - API v1
# =============================================================================

api_v1 = Router(prefix="/api/v1")


@api_v1.get("/info")
async def api_info(request: Request) -> dict:
    """API version information."""
    return {
        "api_version": "0.1.0",
        "framework": "Thor",
    }


@api_v1.get("/products")
async def list_products(request: Request) -> dict:
    """List products."""
    return {
        "products": [
            {"id": 1, "name": "Mjolnir", "price": 999.99},
            {"id": 2, "name": "Stormbreaker", "price": 1299.99},
        ],
    }


# Include the subrouter
app.include_router(api_v1)


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    """Run the Thor application."""
    # Configure structured logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    logger.info("""
    Thor Micro Web Framework
    ============================
    
    Starting development server...
    
    Available endpoints:
    - GET  /              - Hello World
    - GET  /health        - Health check
    - GET  /users/{id}    - Get user by ID
    - POST /users         - Create user
    - GET  /search        - Search with query params
    - GET  /session       - Get session data
    - POST /session       - Update session
    - GET  /cookie-demo   - Cookie demonstration
    - GET  /error         - Error handling demo
    - GET  /api/v1/info   - API info (subrouter)
    - GET  /api/v1/products - List products
    """)

    app.run(
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
