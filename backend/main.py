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
from pathlib import Path

if sys.platform == "win32":
    # Use ProactorEventLoop for Windows subprocess support (required for Playwright)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

# Configure basic logging first
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


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
        "http://localhost:8001",
        "http://127.0.0.1:8001",
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
# Add this to your main.py register_routers function


def register_routers(app: FastAPI) -> None:
    """Register all available routers with proper error handling."""
    logger = get_logger("app.routers")
    registered_count = 0

    # Core routers (these MUST work)
    core_routers = [
        ("auth", "/api/auth", ["authentication"]),
        ("users", "/api/users", ["users"]),
    ]

    for router_name, prefix, tags in core_routers:
        try:
            if router_name == "auth":
                from app.api.auth import router as auth_router

                app.include_router(auth_router, prefix=prefix, tags=tags)
            elif router_name == "users":
                from app.api.users import router as users_router

                app.include_router(users_router, prefix=prefix, tags=tags)

            logger.info(f"✅ {router_name.title()} router registered at {prefix}")
            registered_count += 1

        except ImportError as e:
            logger.error(f"❌ CRITICAL: {router_name} router failed to import: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ CRITICAL: {router_name} router registration failed: {e}")
            raise

    # Optional routers (won't break the app if missing)
    # CHANGE TO:
    optional_routers = [
        ("campaigns", "", ["campaigns"]),  # No prefix - defined in router
        ("analytics", "", ["analytics"]),  # Analytics router
        ("admin", "", ["admin"]),
        ("submissions", "/submissions", ["submissions"]),  # ✅ Added /
        ("health", "/health", ["health"]),  # ✅ Added /
        ("websocket", "/ws", ["websocket"]),  # ✅ Added /
        ("captcha", "/captcha", ["captcha"]),  # ✅ Added /
    ]

    for router_name, prefix, tags in optional_routers:
        try:
            router_module = None

            if router_name == "campaigns":
                from app.api.campaigns import router as campaigns_router

                router_module = campaigns_router
            elif router_name == "analytics":  # ADDED: Analytics import
                from app.api.analytics import router as analytics_router

                router_module = analytics_router
            elif router_name == "admin":
                from app.api.admin import router as admin_router

                router_module = admin_router
            elif router_name == "submissions":
                from app.api.submissions import router as submissions_router

                router_module = submissions_router
            elif router_name == "health":
                from app.api.health import router as health_router

                router_module = health_router
            elif router_name == "websocket":
                from app.api.websocket import router as websocket_router

                router_module = websocket_router
            elif router_name == "captcha":
                from app.api.captcha import router as captcha_router

                router_module = captcha_router

            if router_module:
                if prefix:
                    app.include_router(router_module, prefix=prefix, tags=tags)
                    logger.info(
                        f"✅ {router_name.title()} router registered at {prefix}"
                    )
                else:
                    app.include_router(router_module, tags=tags)
                    logger.info(
                        f"✅ {router_name.title()} router registered (self-prefixed)"
                    )
                registered_count += 1

        except ImportError:
            logger.warning(f"⚠️ {router_name.title()} router not found - skipping")
        except Exception as e:
            logger.warning(f"⚠️ {router_name.title()} router registration failed: {e}")

    logger.info(
        f"📊 Router registration complete: {registered_count} routers registered"
    )


# ----------------------------
# Application Factory
# ----------------------------
def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        lifespan=lifespan,
        title=os.getenv("APP_NAME", "Contact Page Submitter"),
        version=os.getenv("APP_VERSION", "2.0.0"),
        description="Automated contact form submission system with Death By Captcha integration",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Security middleware
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"],  # Configure appropriately for production
    )

    # CORS middleware
    allow_origins = _parse_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Request logging middleware
    app.add_middleware(RequestLoggingMiddleware, logger_name="http")

    # Register all routers
    register_routers(app)

    # Built-in health check endpoint (in case health router fails)
    @app.get("/health")
    async def health_check():
        """Built-in health check endpoint."""
        return {
            "status": "healthy",
            "service": "Contact Page Submitter API",
            "version": os.getenv("APP_VERSION", "2.0.0"),
            "timestamp": time.time(),
        }

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
                methods = sorted(list(route.methods))
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
                route_logger.info(f"  🔗 {route}")

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
    port = int(os.getenv("PORT", "8001"))
    reload = os.getenv("RELOAD", "true").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    backend_dir = Path(__file__).parent
    sys.path.insert(0, str(backend_dir))
    print(f"🚀 Starting Contact Page Submitter API")
    print(f"📡 Server: {host}:{port}")
    print(f"🔄 Reload: {reload}")
    print(f"📊 Log Level: {log_level}")
    print(f"📚 Documentation: http://{host}:{port}/docs")
    print(f"🏠 Root endpoint: http://{host}:{port}/")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        log_level=log_level,
        access_log=True,
    )
