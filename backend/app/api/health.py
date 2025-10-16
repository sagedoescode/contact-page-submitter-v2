"""Enhanced Health Check API endpoints for FastAPI with optimized logging."""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
import psutil
import time
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import asyncio

# Import dependencies - adjust based on your actual project structure
try:
    from app.core.dependencies import get_current_user
    from app.logging import get_logger, log_function
    from app.logging.core import request_id_var, user_id_var
    HAS_AUTH = True
except ImportError:
    import logging
    HAS_AUTH = False
    
    def get_current_user():
        return {"id": "anonymous"}
    
    def get_logger(name):
        return logging.getLogger(name)
    
    def log_function(name):
        def decorator(func):
            return func
        return decorator

# Initialize logger
logger = get_logger(__name__)

# Create FastAPI router
router = APIRouter(
    prefix="/api/health",
    tags=["health"],
    responses={503: {"description": "Service Unavailable"}},
)

# Health check cache
HEALTH_CACHE = {
    "last_check": None, 
    "results": {}, 
    "cache_duration": 10,  # seconds
    "failure_count": 0,
    "last_failure": None
}

# Resource thresholds
RESOURCE_THRESHOLDS = {
    "cpu": {"warning": 80, "critical": 95},
    "memory": {"warning": 80, "critical": 95},
    "disk": {"warning": 80, "critical": 95}
}


# Pydantic models for responses
class HealthStatus(BaseModel):
    status: str
    timestamp: str
    uptime_seconds: Optional[float] = None
    service: Optional[str] = None


class ServiceHealth(BaseModel):
    status: str
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    timestamp: str


class SystemResources(BaseModel):
    cpu: Dict[str, Any]
    memory: Dict[str, Any]
    disk: Dict[str, Any]


class DetailedHealth(BaseModel):
    status: str
    timestamp: str
    services: Dict[str, Any]
    uptime_seconds: float


class ReadinessResponse(BaseModel):
    ready: bool
    timestamp: str
    reason: Optional[str] = None


class LivenessResponse(BaseModel):
    alive: bool
    timestamp: str
    error: Optional[str] = None


class MetricsResponse(BaseModel):
    success: bool
    metrics: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


async def check_database_health() -> Dict[str, Any]:
    """Check database connectivity and performance."""
    start_time = time.time()
    
    try:
        # Replace with actual database check
        # from app.core.database import get_db
        # async with get_db() as db:
        #     await db.execute("SELECT 1")
        
        # Simulated check
        await asyncio.sleep(0.01)  # Simulate DB query
        
        response_time = (time.time() - start_time) * 1000  # Convert to ms
        
        # Only log if slow response
        if response_time > 100:
            logger.warning(
                "Slow database health check",
                extra={"response_time_ms": response_time}
            )
        
        return {
            "status": "healthy",
            "response_time_ms": response_time,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        # Always log database failures - critical for operations
        logger.error(
            "Database health check failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


async def check_redis_health() -> Dict[str, Any]:
    """Check Redis connectivity."""
    try:
        # Replace with actual Redis check
        # import aioredis
        # redis = await aioredis.create_redis_pool('redis://localhost')
        # await redis.ping()
        # redis.close()
        # await redis.wait_closed()
        
        # Simulated check
        await asyncio.sleep(0.01)  # Simulate Redis ping
        
        # No logging for successful Redis checks
        return {
            "status": "healthy", 
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        # Log Redis failures
        logger.error(
            "Redis health check failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


def check_system_resources() -> Dict[str, Any]:
    """Check system resource utilization."""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        
        resources = {
            "cpu": {
                "usage_percent": cpu_percent,
                "status": (
                    "healthy"
                    if cpu_percent < RESOURCE_THRESHOLDS["cpu"]["warning"]
                    else "warning" 
                    if cpu_percent < RESOURCE_THRESHOLDS["cpu"]["critical"] 
                    else "critical"
                ),
            },
            "memory": {
                "usage_percent": memory.percent,
                "available_gb": round(memory.available / (1024**3), 2),
                "total_gb": round(memory.total / (1024**3), 2),
                "status": (
                    "healthy"
                    if memory.percent < RESOURCE_THRESHOLDS["memory"]["warning"]
                    else "warning" 
                    if memory.percent < RESOURCE_THRESHOLDS["memory"]["critical"] 
                    else "critical"
                ),
            },
            "disk": {
                "usage_percent": disk.percent,
                "available_gb": round(disk.free / (1024**3), 2),
                "total_gb": round(disk.total / (1024**3), 2),
                "status": (
                    "healthy"
                    if disk.percent < RESOURCE_THRESHOLDS["disk"]["warning"]
                    else "warning" 
                    if disk.percent < RESOURCE_THRESHOLDS["disk"]["critical"] 
                    else "critical"
                ),
            },
        }
        
        # Only log critical resource issues
        if cpu_percent >= RESOURCE_THRESHOLDS["cpu"]["critical"]:
            logger.critical(
                "Critical CPU usage",
                extra={"cpu_percent": cpu_percent}
            )
        elif memory.percent >= RESOURCE_THRESHOLDS["memory"]["critical"]:
            logger.critical(
                "Critical memory usage",
                extra={"memory_percent": memory.percent}
            )
        elif disk.percent >= RESOURCE_THRESHOLDS["disk"]["critical"]:
            logger.critical(
                "Critical disk usage",
                extra={"disk_percent": disk.percent}
            )
        
        return resources
        
    except Exception as e:
        logger.error(
            "System resource check failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        return {"status": "error", "error": str(e)}


@router.get("/check", response_model=HealthStatus)
async def basic_health_check(request: Request):
    """Basic health check endpoint - minimal logging."""
    try:
        # No logging for basic health checks unless they fail
        # These are called frequently by load balancers
        
        return HealthStatus(
            status="healthy",
            service="api",
            timestamp=datetime.utcnow().isoformat(),
            uptime_seconds=time.time() - psutil.boot_time(),
        )
    
    except Exception as e:
        logger.error(
            "Basic health check failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


@router.get("/detailed", response_model=DetailedHealth)
@log_function("detailed_health_check")
async def detailed_health_check(request: Request):
    """Detailed health check with all service dependencies."""
    try:
        # Check cache first
        if HEALTH_CACHE["last_check"]:
            cache_age = time.time() - HEALTH_CACHE["last_check"]
            if cache_age < HEALTH_CACHE["cache_duration"]:
                # Return cached results without logging
                return HEALTH_CACHE["results"]
        
        # Perform all health checks
        database_health, redis_health = await asyncio.gather(
            check_database_health(), 
            check_redis_health()
        )
        
        checks = {
            "database": database_health,
            "redis": redis_health,
            "system": check_system_resources(),
        }
        
        # Determine overall health
        overall_status = "healthy"
        unhealthy_services = []
        
        for service, status in checks.items():
            if isinstance(status, dict):
                if status.get("status") == "critical":
                    overall_status = "critical"
                    unhealthy_services.append(service)
                elif status.get("status") == "unhealthy" and overall_status != "critical":
                    overall_status = "degraded"
                    unhealthy_services.append(service)
        
        response = DetailedHealth(
            status=overall_status,
            timestamp=datetime.utcnow().isoformat(),
            services=checks,
            uptime_seconds=time.time() - psutil.boot_time(),
        )
        
        # Update cache
        HEALTH_CACHE["last_check"] = time.time()
        HEALTH_CACHE["results"] = response
        
        # Only log if status changed or unhealthy
        if overall_status != "healthy":
            if overall_status != HEALTH_CACHE.get("last_status"):
                logger.warning(
                    "Health status changed",
                    extra={
                        "new_status": overall_status,
                        "previous_status": HEALTH_CACHE.get("last_status", "unknown"),
                        "unhealthy_services": unhealthy_services
                    }
                )
            HEALTH_CACHE["last_status"] = overall_status
            HEALTH_CACHE["failure_count"] += 1
            HEALTH_CACHE["last_failure"] = time.time()
            
            raise HTTPException(status_code=503, detail=response.dict())
        else:
            # Reset failure tracking on recovery
            if HEALTH_CACHE.get("last_status") != "healthy" and HEALTH_CACHE["failure_count"] > 0:
                logger.info(
                    "Health recovered",
                    extra={
                        "failure_count": HEALTH_CACHE["failure_count"],
                        "downtime_seconds": time.time() - HEALTH_CACHE.get("last_failure", time.time())
                    }
                )
                HEALTH_CACHE["failure_count"] = 0
                HEALTH_CACHE["last_failure"] = None
            
            HEALTH_CACHE["last_status"] = overall_status
        
        return response
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Detailed health check error",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


@router.get("/readiness", response_model=ReadinessResponse)
async def readiness_check(request: Request):
    """Kubernetes readiness probe endpoint - minimal logging."""
    try:
        # Check if service is ready to accept traffic
        db_health = await check_database_health()
        
        if db_health["status"] == "healthy":
            # No logging for successful readiness checks
            return ReadinessResponse(
                ready=True, 
                timestamp=datetime.utcnow().isoformat()
            )
        else:
            # Log readiness failures
            logger.warning(
                "Readiness check failed",
                extra={"reason": "database_unhealthy"}
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "ready": False,
                    "reason": "Database not ready",
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Readiness check error",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


@router.get("/liveness", response_model=LivenessResponse)
async def liveness_check(request: Request):
    """Kubernetes liveness probe endpoint - no logging."""
    try:
        # Never log successful liveness checks - too frequent
        return LivenessResponse(
            alive=True, 
            timestamp=datetime.utcnow().isoformat()
        )
    
    except Exception as e:
        # Only log if liveness fails (critical issue)
        logger.critical(
            "Liveness check failed",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=503,
            detail={
                "alive": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


@router.get("/metrics", response_model=MetricsResponse)
@log_function("get_health_metrics")
async def get_health_metrics(
    request: Request,
    current_user: Optional[Dict] = Depends(get_current_user) if HAS_AUTH else None,
):
    """Get detailed health metrics (admin only)."""
    try:
        user_id = current_user.get("id") if current_user else "anonymous"
        
        if HAS_AUTH and user_id:
            user_id_var.set(user_id)
        
        # TODO: Add admin check
        # if not is_admin(user_id):
        #     raise HTTPException(status_code=403, detail="Unauthorized")
        
        # Collect detailed metrics
        database_health, redis_health = await asyncio.gather(
            check_database_health(), 
            check_redis_health()
        )
        
        process = psutil.Process()
        
        metrics = {
            "system": check_system_resources(),
            "services": {
                "database": database_health, 
                "redis": redis_health
            },
            "process": {
                "pid": os.getpid(),
                "cpu_percent": process.cpu_percent(),
                "memory_mb": round(process.memory_info().rss / (1024**2), 2),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()) if hasattr(process, 'open_files') else 0,
            },
            "cache": {
                "last_check": HEALTH_CACHE.get("last_check"),
                "failure_count": HEALTH_CACHE.get("failure_count", 0),
                "last_failure": HEALTH_CACHE.get("last_failure"),
                "last_status": HEALTH_CACHE.get("last_status", "unknown")
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Log metrics access for audit
        if user_id != "anonymous":
            logger.info(
                "Health metrics accessed",
                extra={
                    "user_id": user_id,
                    "failure_count": HEALTH_CACHE.get("failure_count", 0)
                }
            )
        
        return MetricsResponse(success=True, metrics=metrics)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get health metrics",
            extra={
                "error": str(e),
                "error_type": type(e).__name__
            },
            exc_info=True
        )
        return MetricsResponse(
            success=False, 
            error="Failed to retrieve metrics"
        )


@router.get("/ping")
async def ping():
    """Simple ping endpoint for quick checks - never logged."""
    return {"pong": True, "timestamp": datetime.utcnow().isoformat()}