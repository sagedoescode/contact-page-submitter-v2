# backend/app/core/cache.py - Optimized cache with smart logging
import json
import redis
import time
from typing import Optional, Dict, Any, List, Literal, Union
from datetime import timedelta
from app.logging import get_logger

logger = get_logger(__name__)

# Connection configuration
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_TIMEOUT = 5

# Performance thresholds (ms)
SLOW_OPERATION_THRESHOLD = 100  # Log if operation takes >100ms
CONNECTION_RETRY_DELAY = 5  # Seconds between connection retry logs

# Track connection state to avoid log spam
_last_connection_error_time = 0
_connection_error_count = 0
_is_connected = True

# Statistics for monitoring
_cache_stats = {
    "hits": 0,
    "misses": 0,
    "sets": 0,
    "errors": 0,
}

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=REDIS_TIMEOUT,
    socket_timeout=REDIS_TIMEOUT,
)


def _log_connection_error(operation: str, error: Exception):
    """Log connection errors with rate limiting to avoid spam."""
    global _last_connection_error_time, _connection_error_count, _is_connected

    current_time = time.time()
    time_since_last_error = current_time - _last_connection_error_time

    # Only log if it's the first error or enough time has passed
    if time_since_last_error > CONNECTION_RETRY_DELAY:
        _connection_error_count += 1

        logger.error(
            "Redis connection failed",
            extra={
                "event": "cache_connection_failed",
                "operation": operation,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "consecutive_failures": _connection_error_count,
                "host": REDIS_HOST,
                "port": REDIS_PORT,
            },
            exc_info=False,  # Don't need full stack trace for connection issues
        )

        _last_connection_error_time = current_time
        _is_connected = False


def _log_connection_restored():
    """Log when connection is restored after failures."""
    global _connection_error_count, _is_connected

    if not _is_connected and _connection_error_count > 0:
        logger.info(
            "Redis connection restored",
            extra={
                "event": "cache_connection_restored",
                "total_failures": _connection_error_count,
            },
        )
        _connection_error_count = 0
        _is_connected = True


def cache_get(key: str) -> Optional[Any]:
    """Get value from cache with smart logging."""
    start_time = time.time()

    try:
        value = redis_client.get(key)
        duration_ms = (time.time() - start_time) * 1000

        if value:
            _cache_stats["hits"] += 1
            result = json.loads(value)

            # Log connection restored if this is first success after failures
            _log_connection_restored()

            # Only log slow cache reads
            if duration_ms > SLOW_OPERATION_THRESHOLD:
                logger.warning(
                    "Slow cache read",
                    extra={
                        "event": "cache_get_slow",
                        "key": key,
                        "duration_ms": round(duration_ms, 2),
                        "hit": True,
                    },
                )

            return result
        else:
            _cache_stats["misses"] += 1

            # Log connection restored
            _log_connection_restored()

            # Only log slow misses
            if duration_ms > SLOW_OPERATION_THRESHOLD:
                logger.warning(
                    "Slow cache miss",
                    extra={
                        "event": "cache_get_slow",
                        "key": key,
                        "duration_ms": round(duration_ms, 2),
                        "hit": False,
                    },
                )

            return None

    except redis.RedisError as e:
        _cache_stats["errors"] += 1
        _log_connection_error("get", e)
        return None

    except json.JSONDecodeError as e:
        # Data corruption - always log this
        logger.error(
            "Cache data corruption",
            extra={
                "event": "cache_decode_error",
                "key": key,
                "error_message": str(e),
            },
            exc_info=True,
        )
        # Try to delete corrupted key
        try:
            redis_client.delete(key)
        except:
            pass
        return None

    except Exception as e:
        # Unexpected errors - always log
        logger.error(
            "Unexpected cache error",
            extra={
                "event": "cache_unexpected_error",
                "operation": "get",
                "key": key,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        return None


def cache_set(key: str, value: Any, expire: int = 5):
    """Set value in cache with expiration in seconds and smart logging."""
    start_time = time.time()

    try:
        serialized = json.dumps(value)
        redis_client.setex(key, timedelta(seconds=expire), serialized)

        duration_ms = (time.time() - start_time) * 1000
        _cache_stats["sets"] += 1

        # Log connection restored if this is first success after failures
        _log_connection_restored()

        # Only log slow cache writes
        if duration_ms > SLOW_OPERATION_THRESHOLD:
            logger.warning(
                "Slow cache write",
                extra={
                    "event": "cache_set_slow",
                    "key": key,
                    "duration_ms": round(duration_ms, 2),
                    "value_size": len(serialized),
                    "expire_seconds": expire,
                },
            )

    except redis.RedisError as e:
        _cache_stats["errors"] += 1
        _log_connection_error("set", e)

    except json.JSONEncodeError as e:
        # Serialization errors - always log
        logger.error(
            "Cache serialization failed",
            extra={
                "event": "cache_encode_error",
                "key": key,
                "value_type": type(value).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )

    except Exception as e:
        # Unexpected errors - always log
        logger.error(
            "Unexpected cache error",
            extra={
                "event": "cache_unexpected_error",
                "operation": "set",
                "key": key,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )


def cache_delete(key: str) -> bool:
    """Delete a key from cache."""
    try:
        result = redis_client.delete(key)
        _log_connection_restored()
        return bool(result)
    except redis.RedisError as e:
        _cache_stats["errors"] += 1
        _log_connection_error("delete", e)
        return False
    except Exception as e:
        logger.error(
            "Unexpected cache error",
            extra={
                "event": "cache_unexpected_error",
                "operation": "delete",
                "key": key,
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        return False


def cache_exists(key: str) -> bool:
    """Check if a key exists in cache."""
    try:
        result = redis_client.exists(key)
        _log_connection_restored()
        return bool(result)
    except redis.RedisError as e:
        _log_connection_error("exists", e)
        return False


def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics for monitoring."""
    total_operations = _cache_stats["hits"] + _cache_stats["misses"]
    hit_rate = (
        (_cache_stats["hits"] / total_operations * 100) if total_operations > 0 else 0
    )

    stats = {
        **_cache_stats,
        "total_operations": total_operations,
        "hit_rate_percent": round(hit_rate, 2),
        "is_connected": _is_connected,
    }

    # Log statistics if hit rate is concerning (only when we have enough data)
    if total_operations > 100 and hit_rate < 30:
        logger.warning(
            "Low cache hit rate detected",
            extra={
                "event": "cache_low_hit_rate",
                **stats,
            },
        )

    return stats


def reset_cache_stats():
    """Reset cache statistics (useful for monitoring intervals)."""
    global _cache_stats
    old_stats = _cache_stats.copy()

    _cache_stats = {
        "hits": 0,
        "misses": 0,
        "sets": 0,
        "errors": 0,
    }

    return old_stats


def cache_health_check() -> Dict[str, Any]:
    """Perform a health check on the cache."""
    start_time = time.time()

    try:
        # Try a simple operation
        test_key = "_health_check_"
        test_value = {"test": True, "timestamp": time.time()}

        redis_client.setex(test_key, timedelta(seconds=1), json.dumps(test_value))
        retrieved = redis_client.get(test_key)
        redis_client.delete(test_key)

        duration_ms = (time.time() - start_time) * 1000

        return {
            "healthy": True,
            "duration_ms": round(duration_ms, 2),
            "host": REDIS_HOST,
            "port": REDIS_PORT,
        }

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Cache health check failed",
            extra={
                "event": "cache_health_check_failed",
                "duration_ms": round(duration_ms, 2),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )

        return {
            "healthy": False,
            "duration_ms": round(duration_ms, 2),
            "error": str(e),
            "host": REDIS_HOST,
            "port": REDIS_PORT,
        }
