# app/core/database.py - Optimized database configuration with smart logging
"""Database configuration with connection monitoring and performance tracking."""

from __future__ import annotations

from sqlalchemy import create_engine, MetaData, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import Pool
from typing import Generator
import time
from app.logging import get_logger

from app.core.config import get_settings

# Setup logger
logger = get_logger(__name__)

settings = get_settings()

# Track initialization state
_db_initialized = False
_engine_created = False

# Create database engine
try:
    start_time = time.time()

    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=False,  # Don't echo SQL (use DEBUG logging level instead)
    )

    duration_ms = (time.time() - start_time) * 1000

    # Log engine creation only once
    logger.info(
        "Database engine created",
        extra={
            "event": "db_engine_created",
            "duration_ms": round(duration_ms, 2),
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,
        },
    )
    _engine_created = True

except Exception as e:
    logger.error(
        "Database engine creation failed",
        extra={
            "event": "db_engine_failed",
            "error_type": type(e).__name__,
            "error_message": str(e),
        },
        exc_info=True,
    )
    raise

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models with naming convention
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)
Base = declarative_base(metadata=metadata)

# Connection pool monitoring
_pool_stats = {
    "checkouts": 0,
    "connects": 0,
    "disconnects": 0,
    "slow_checkouts": 0,
}


@event.listens_for(Pool, "connect")
def receive_connect(dbapi_conn, connection_record):
    """Track new database connections."""
    _pool_stats["connects"] += 1

    # Only log if connection count is high (potential leak)
    if _pool_stats["connects"] > 100 and _pool_stats["connects"] % 50 == 0:
        logger.warning(
            "High connection count detected",
            extra={
                "event": "db_high_connects",
                "total_connects": _pool_stats["connects"],
                "disconnects": _pool_stats["disconnects"],
                "active_connections": _pool_stats["connects"]
                - _pool_stats["disconnects"],
            },
        )


@event.listens_for(Pool, "checkout")
def receive_checkout(dbapi_conn, connection_record, connection_proxy):
    """Track connection checkouts from pool."""
    connection_record.checkout_time = time.time()
    _pool_stats["checkouts"] += 1


@event.listens_for(Pool, "checkin")
def receive_checkin(dbapi_conn, connection_record):
    """Track connection checkins and detect slow operations."""
    if hasattr(connection_record, "checkout_time"):
        duration_ms = (time.time() - connection_record.checkout_time) * 1000

        # Only log slow database operations (>1000ms)
        if duration_ms > 1000:
            _pool_stats["slow_checkouts"] += 1
            logger.warning(
                "Slow database operation detected",
                extra={
                    "event": "db_slow_operation",
                    "duration_ms": round(duration_ms, 2),
                    "total_slow_ops": _pool_stats["slow_checkouts"],
                },
            )


@event.listens_for(Pool, "close")
def receive_close(dbapi_conn, connection_record):
    """Track connection closes."""
    _pool_stats["disconnects"] += 1


def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session.
    Ensures proper cleanup after use.
    No logging - this is called on every request.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        # Only log database session errors
        logger.error(
            "Database session error",
            extra={
                "event": "db_session_error",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise
    finally:
        db.close()


def init_db() -> None:
    """
    Initialize database by creating all tables.
    Import all models first to register them with Base.
    """
    global _db_initialized

    if _db_initialized:
        logger.warning(
            "Database already initialized", extra={"event": "db_init_duplicate"}
        )
        return

    start_time = time.time()

    # Import ALL models to register them with SQLAlchemy
    try:
        import app.models
        from app.models.subscription import SubscriptionPlan, Subscription
        from app.models.settings import Settings
        from app.models.user import User
        from app.models.campaign import Campaign
        from app.models.website import Website
        from app.models.submission import Submission
        from app.models.user_profile import UserProfile
        from app.models.logs import Log, SubmissionLog, CaptchaLog, SystemLog

    except Exception as e:
        logger.error(
            "Model import failed during database initialization",
            extra={
                "event": "db_init_import_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        # Continue anyway - some models might have loaded

    try:
        # Create all tables
        Base.metadata.create_all(bind=engine)

        duration_ms = (time.time() - start_time) * 1000

        logger.info(
            "Database initialized",
            extra={
                "event": "db_initialized",
                "duration_ms": round(duration_ms, 2),
                "tables_created": True,
            },
        )

        # Create default subscription plans if needed
        _create_default_plans()

        _db_initialized = True

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Database initialization failed",
            extra={
                "event": "db_init_failed",
                "duration_ms": round(duration_ms, 2),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise


def _create_default_plans():
    """Create default subscription plans if they don't exist."""
    db = SessionLocal()
    start_time = time.time()

    try:
        from app.models.subscription import SubscriptionPlan
        import uuid
        from decimal import Decimal

        # Check if plans exist
        existing_plans = db.query(SubscriptionPlan).count()

        if existing_plans == 0:
            # Create default plans with proper data types
            plans_data = [
                {
                    "id": uuid.uuid4(),
                    "name": "Free",
                    "description": "Basic plan for getting started",
                    "max_websites": 10,
                    "max_submissions_per_day": 50,
                    "price": Decimal("0.00"),
                    "features": {"basic_support": True, "captcha_solving": False},
                },
                {
                    "id": uuid.uuid4(),
                    "name": "Pro",
                    "description": "Professional plan for growing businesses",
                    "max_websites": 100,
                    "max_submissions_per_day": 500,
                    "price": Decimal("49.99"),
                    "features": {
                        "priority_support": True,
                        "captcha_solving": True,
                        "proxy_support": True,
                    },
                },
                {
                    "id": uuid.uuid4(),
                    "name": "Enterprise",
                    "description": "Unlimited plan for large organizations",
                    "max_websites": None,  # NULL for unlimited
                    "max_submissions_per_day": None,  # NULL for unlimited
                    "price": Decimal("199.99"),
                    "features": {
                        "dedicated_support": True,
                        "captcha_solving": True,
                        "proxy_support": True,
                        "api_access": True,
                        "custom_integrations": True,
                    },
                },
            ]

            # Create plan objects
            plans = []
            for plan_data in plans_data:
                plan = SubscriptionPlan(**plan_data)
                plans.append(plan)
                db.add(plan)

            # Commit the transaction
            db.commit()

            duration_ms = (time.time() - start_time) * 1000

            logger.info(
                "Default subscription plans created",
                extra={
                    "event": "db_plans_created",
                    "plan_count": len(plans),
                    "duration_ms": round(duration_ms, 2),
                },
            )

        # No log if plans already exist (routine check)

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Failed to create default subscription plans",
            extra={
                "event": "db_plans_failed",
                "duration_ms": round(duration_ms, 2),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        db.rollback()
        raise
    finally:
        db.close()


def test_db_connection() -> bool:
    """Test database connection with performance tracking."""
    start_time = time.time()

    try:
        db = SessionLocal()
        # Try a simple query
        db.execute("SELECT 1")
        db.close()

        duration_ms = (time.time() - start_time) * 1000

        # Only log slow connection tests (>500ms)
        if duration_ms > 500:
            logger.warning(
                "Slow database connection test",
                extra={
                    "event": "db_test_slow",
                    "duration_ms": round(duration_ms, 2),
                },
            )

        return True

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Database connection test failed",
            extra={
                "event": "db_test_failed",
                "duration_ms": round(duration_ms, 2),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        return False


def get_db_info() -> dict:
    """Get database connection information with safe URL masking."""
    try:
        db = SessionLocal()
        result = db.execute("SELECT version()").fetchone()
        db.close()

        # Mask the database URL for security
        masked_url = (
            settings.DATABASE_URL.split("@")[-1]
            if "@" in settings.DATABASE_URL
            else "Hidden"
        )

        return {
            "connected": True,
            "version": result[0] if result else "Unknown",
            "url": masked_url,
            "pool_size": engine.pool.size(),
            "pool_stats": _pool_stats.copy(),
        }

    except Exception as e:
        logger.error(
            "Failed to get database info",
            extra={
                "event": "db_info_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        return {"connected": False, "error": str(e), "url": "Connection failed"}


def get_pool_stats() -> dict:
    """Get detailed connection pool statistics."""
    try:
        pool = engine.pool

        stats = {
            **_pool_stats,
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "active_connections": _pool_stats["connects"] - _pool_stats["disconnects"],
        }

        # Calculate utilization
        total_capacity = 10 + 20  # pool_size + max_overflow
        current_usage = stats["checked_out"]
        utilization_percent = (
            (current_usage / total_capacity * 100) if total_capacity > 0 else 0
        )
        stats["utilization_percent"] = round(utilization_percent, 2)

        # Log warning if pool utilization is high
        if utilization_percent > 80:
            logger.warning(
                "High database pool utilization",
                extra={
                    "event": "db_pool_high_utilization",
                    **stats,
                },
            )

        return stats

    except Exception as e:
        logger.error(
            "Failed to get pool statistics",
            extra={
                "event": "db_pool_stats_failed",
                "error_type": type(e).__name__,
            },
        )
        return {"error": str(e)}


def reset_pool_stats():
    """Reset pool statistics (useful for monitoring intervals)."""
    global _pool_stats

    old_stats = _pool_stats.copy()

    _pool_stats = {
        "checkouts": 0,
        "connects": 0,
        "disconnects": 0,
        "slow_checkouts": 0,
    }

    return old_stats
