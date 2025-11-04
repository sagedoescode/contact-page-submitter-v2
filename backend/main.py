# app/main.py - Complete end-to-end solution with proper router registration
"""
FastAPI entrypoint with proper model initialization and Windows ProactorEventLoop policy.
Complete end-to-end solution for Contact Page Submitter.
"""

# --- MUST be first: use ProactorEventLoop on Windows for Playwright subprocess support
import sys
import asyncio
import os
import logging
import time

if sys.platform == "win32":
    # Use ProactorEventLoop for Windows subprocess support (required for Playwright)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Set environment variables BEFORE any imports
os.environ["SQLALCHEMY_ECHO"] = "false"
os.environ["SQLALCHEMY_WARN_20"] = "0"
os.environ["PYTHONWARNINGS"] = "ignore"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Suppress SQLAlchemy logs
logging.getLogger("sqlalchemy").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.pool").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.dialects").setLevel(logging.ERROR)
logging.getLogger("sqlalchemy.orm").setLevel(logging.ERROR)

from pathlib import Path
import sys


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)


# --- Initialize database (this will import all models in correct order)
from app.core.database import init_db


# ----------------------------
# Helpers
# ----------------------------
def _parse_cors_origins() -> list[str]:
    """Parse CORS_ORIGINS environment variable."""
    default_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return default_origins

    if raw == "*":
        return ["*"]

    try:
        import json

        val = json.loads(raw)
        if isinstance(val, list):
            return [str(x) for x in val]
    except Exception:
        pass

    # Split by comma and clean
    origins = [s.strip() for s in raw.split(",") if s.strip()]
    return origins or default_origins


# ----------------------------
# Request Logging Middleware
# ----------------------------
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log HTTP requests."""

    def __init__(self, app, logger_name: str = "http"):
        super().__init__(app)
        self.logger = get_logger(logger_name)

    async def dispatch(self, request: Request, call_next):
        # Generate request ID
        import uuid

        request_id = str(uuid.uuid4())[:8]

        # Log request start
        start_time = time.time()
        self.logger.info(
            f"Request started: {request.method} {request.url.path} [req:{request_id}]"
        )

        # Process request
        try:
            response = await call_next(request)

            # Log successful response
            duration_ms = (time.time() - start_time) * 1000
            self.logger.info(
                f"Request completed: {response.status_code} in {duration_ms:.2f}ms [req:{request_id}]"
            )

            return response

        except Exception as e:
            # Log error
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(
                f"Request failed: {str(e)} in {duration_ms:.2f}ms [req:{request_id}]"
            )
            raise


# ----------------------------
# Lifespan Management
# ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    logger = get_logger("app.main")
    logger.info("Application starting up")

    # Initialize database tables and create default data
    try:
        init_db()
        logger.info("✅ Database initialized successfully")

        # Log event loop policy for debugging
        policy = asyncio.get_event_loop_policy()
        logger.info(f"Event loop policy: {type(policy).__name__}")

        logger.info(
            "CAPTCHA integration: Death By Captcha support enabled via user profiles"
        )

    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise

    yield

    # Shutdown
    logger.info("Application shutting down")


# ----------------------------
# Router Registration Function
# ----------------------------
def register_routers(app: FastAPI) -> None:
    """Register all available routers with proper error handling."""
    logger = get_logger("app.routers")
    logger.info("Starting router registration process...")
    registered_count = 0

    # Test campaigns router specifically
    logger.info("Attempting to register campaigns router...")
    try:
        from app.api.campaigns import router as campaigns_router

        logger.info(
            f"Campaigns router imported successfully. Routes: {len(campaigns_router.routes)}"
        )
        logger.info(
            f"Campaigns router prefix: {getattr(campaigns_router, 'prefix', 'None')}"
        )

        # Don't add prefix - the router already has one
        app.include_router(campaigns_router)
        logger.info("✅ Campaigns router registered successfully")
        registered_count += 1
    except ImportError as e:
        logger.error(f"❌ Failed to import campaigns router: {e}")
    except Exception as e:
        logger.error(f"❌ Failed to register campaigns router: {e}")
        import traceback

        logger.error(traceback.format_exc())

    # Test analytics router specifically
    logger.info("Attempting to register analytics router...")
    try:
        from app.api.analytics import router as analytics_router

        logger.info(
            f"Analytics router imported successfully. Routes: {len(analytics_router.routes)}"
        )
        logger.info(
            f"Analytics router prefix: {getattr(analytics_router, 'prefix', 'None')}"
        )

        # Don't add prefix - the router already has one
        app.include_router(analytics_router)
        logger.info("✅ Analytics router registered successfully")
        registered_count += 1
    except ImportError as e:
        logger.error(f"❌ Failed to import analytics router: {e}")
    except Exception as e:
        logger.error(f"❌ Failed to register analytics router: {e}")
        import traceback

        logger.error(traceback.format_exc())

    # Auth router (keep existing logic)
    try:
        from app.api.auth import router as auth_router

        # Check if auth router already has a prefix
        if hasattr(auth_router, "prefix") and auth_router.prefix:
            app.include_router(auth_router)
            logger.info(
                f"✅ Auth router registered with existing prefix: {auth_router.prefix}"
            )
        else:
            app.include_router(auth_router, prefix="/api/auth", tags=["authentication"])
            logger.info("✅ Auth router registered at /api/auth")
        registered_count += 1
    except Exception as e:
        logger.error(f"❌ Auth router failed: {e}")
        raise

    # Users router (keep existing logic)
    try:
        from app.api.users import router as users_router

        if hasattr(users_router, "prefix") and users_router.prefix:
            app.include_router(users_router)
            logger.info(
                f"✅ Users router registered with existing prefix: {users_router.prefix}"
            )
        else:
            app.include_router(users_router, prefix="/api/users", tags=["users"])
            logger.info("✅ Users router registered at /api/users")
        registered_count += 1
    except Exception as e:
        logger.error(f"❌ Users router failed: {e}")

    logger.info(
        f"📊 Router registration complete: {registered_count} routers registered"
    )


# ----------------------------
# Application Factory
# ----------------------------
def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    logger = get_logger("app.main")

    app = FastAPI(
        lifespan=lifespan,
        title=os.getenv("APP_NAME", "Contact Page Submitter"),
        version=os.getenv("APP_VERSION", "2.0.0"),
        description="Automated contact form submission system with Death By Captcha integration",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Request logging middleware (add first, runs last)
    app.add_middleware(RequestLoggingMiddleware, logger_name="http")
    
    # CORS middleware - Add LAST so it runs FIRST (middleware executes in reverse order)
    allow_origins = _parse_cors_origins()
    print(f"\n{'='*60}")
    print(f"[CORS] Configuring CORS with allowed origins:")
    for origin in allow_origins:
        print(f"[CORS]   - {origin}")
    print(f"{'='*60}\n")
    logger.info(f"[CORS] Configuring CORS with allowed origins: {allow_origins}")
    
    # Add CORS middleware LAST so it processes requests FIRST
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,  # List of allowed origins
        allow_credentials=True,
        allow_methods=["*"],  # Allow all methods
        allow_headers=["*"],  # Allow all headers
        expose_headers=["*"],
        max_age=3600,
    )
    print("[CORS] ✅ CORS middleware configured successfully\n")
    logger.info("[CORS] CORS middleware configured successfully")

    # Register all routers
    register_routers(app)

    # Built-in health check endpoint
    @app.get("/health")
    async def health_check():
        """Built-in health check endpoint."""
        return {
            "status": "healthy",
            "service": "Contact Page Submitter API",
            "version": os.getenv("APP_VERSION", "2.0.0"),
            "timestamp": time.time(),
        }
    
    # CORS test endpoint
    @app.options("/api/auth/login")
    @app.options("/api/{path:path}")
    async def cors_test(request: Request):
        """Explicit CORS handler for testing"""
        origin = request.headers.get("origin")
        allow_origins = _parse_cors_origins()
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Max-Age": "3600",
        }
        if origin in allow_origins:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
        return Response(status_code=200, headers=headers)

    # Root endpoint with comprehensive information
    @app.get("/")
    async def root():
        """Root endpoint with system information."""
        return {
            "name": os.getenv("APP_NAME", "Contact Page Submitter"),
            "version": os.getenv("APP_VERSION", "2.0.0"),
            "status": "operational",
            "description": "Automated contact form submission system",
            "features": {
                "authentication": "JWT-based user authentication",
                "campaigns": "Campaign creation and management",
                "automation": "Automated form submission with browser automation",
                "captcha": "Death By Captcha integration (user-specific)",
                "fallback": "Email extraction when forms not found",
                "tracking": "Real-time progress monitoring",
                "analytics": "Campaign performance metrics",
                "browser": "Playwright-based browser automation",
            },
            "captcha_integration": {
                "provider": "Death By Captcha",
                "configuration": "Per-user credentials in user profiles",
                "success_rate": "95% with CAPTCHA solving vs 60% without",
            },
            "browser_automation": {
                "engine": "Playwright + Chromium",
                "headless": os.getenv("BROWSER_HEADLESS", "true").lower() == "true",
                "visible": os.getenv("DEV_AUTOMATION_HEADFUL", "false").lower()
                == "true",
                "rate": "Up to 120 websites per hour",
            },
            "endpoints": {
                "documentation": "/docs",
                "health_check": "/health",
                "api_auth": "/api/auth/*",
                "api_campaigns": "/api/campaigns/*",
                "api_users": "/api/users/*",
                "api_analytics": "/api/analytics/*",
                "api_admin": "/api/admin/*",
            },
        }

    # Debug endpoint to check loaded routes
    @app.get("/debug/routes")
    async def debug_routes():
        """Debug endpoint to list all registered routes."""
        routes_info = []
        for route in app.router.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                route_info = {
                    "path": route.path,
                    "methods": list(route.methods) if route.methods else [],
                    "name": route.name if hasattr(route, "name") else None,
                    "endpoint": (
                        str(route.endpoint) if hasattr(route, "endpoint") else None
                    ),
                }
                routes_info.append(route_info)

        return {
            "total_routes": len(routes_info),
            "routes": sorted(routes_info, key=lambda x: x["path"]),
        }

    # Add startup event to log registered routes
    @app.on_event("startup")
    async def log_registered_routes():
        """Log all registered routes on startup."""
        route_logger = get_logger("app.routes")
        route_count = 0

        # Group routes by prefix for better readability
        routes_by_prefix = {}

        for route in app.router.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                methods = sorted(list(route.methods)) if route.methods else []
                path = route.path

                # Group by prefix
                prefix = "/" + path.split("/")[1] if len(path.split("/")) > 1 else "/"
                if prefix not in routes_by_prefix:
                    routes_by_prefix[prefix] = []

                routes_by_prefix[prefix].append(f"{' '.join(methods)} {path}")
                route_count += 1

        # Log routes grouped by prefix
        for prefix in sorted(routes_by_prefix.keys()):
            route_logger.info(f"📁 Routes for {prefix}:")
            for route in sorted(routes_by_prefix[prefix]):
                route_logger.info(f"  📗 {route}")

        route_logger.info(f"✅ Total registered routes: {route_count}")

    return app


# ----------------------------
# Create ASGI Application
# ----------------------------
app = create_app()


# ----------------------------
# Development Server
# ----------------------------
if __name__ == "__main__":
    import uvicorn

    # Configuration from environment
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "true").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info").lower()

    print(f"🚀 Starting Contact Page Submitter API")
    print(f"📡 Server: {host}:{port}")
    print(f"🔄 Reload: {reload}")
    print(f"📊 Log Level: {log_level}")
    print(f"📚 Documentation: http://{host}:{port}/docs")
    print(f"🏠 Root endpoint: http://{host}:{port}/")
    print(f"🐛 Debug routes: http://{host}:{port}/debug/routes")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        log_level=log_level,
        access_log=True,
    )
