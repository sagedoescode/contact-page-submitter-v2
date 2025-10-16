"""Enhanced Logs API endpoints with optimized logging."""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import time
import json
import gzip
import csv
import re
from io import StringIO

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.log_service import LogService as ApplicationInsightsLogger
from app.logging import get_logger, log_function
from app.logging.core import request_id_var, user_id_var, campaign_id_var

# Initialize structured logger
logger = get_logger(__name__)

# Create FastAPI router
router = APIRouter(prefix="/api/logs", tags=["logs"], redirect_slashes=False)

# Simulated log storage (in production, use proper log management system)
LOG_BUFFER = []
MAX_LOG_BUFFER = 10000

# Cache for frequent queries
STATS_CACHE = {"last_update": None, "data": None, "ttl": 60}  # seconds


def get_client_ip(request: Request) -> str:
    """Extract client IP from request headers."""
    if not request:
        return "unknown"

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    return request.client.host if request.client else "unknown"


def validate_log_access(user: User, log_level: str = None) -> bool:
    """Validate if user has access to view logs."""
    # Implement your access control logic here
    # For now, basic validation
    user_id = str(user.id)

    # Only log sensitive access attempts
    if log_level in ["CRITICAL", "SECURITY"]:
        logger.security_event(
            event="sensitive_log_access",
            severity="info",
            properties={
                "user_id": user_id,
                "log_level": log_level,
            },
        )

    return True  # Implement actual permission check


def parse_log_query(query_params: dict) -> Dict[str, Any]:
    """Parse and validate log query parameters."""
    parsed = {
        "level": query_params.get("level", "INFO").upper(),
        "start_time": None,
        "end_time": None,
        "source": query_params.get("source"),
        "user_id": query_params.get("user_id"),
        "limit": min(int(query_params.get("limit", 100)), 1000),
        "offset": int(query_params.get("offset", 0)),
        "search": query_params.get("search"),
        "format": query_params.get("format", "json"),
    }

    # Parse time parameters
    if query_params.get("start_time"):
        try:
            parsed["start_time"] = datetime.fromisoformat(query_params["start_time"])
        except ValueError:
            pass  # Invalid format, use None

    if query_params.get("end_time"):
        try:
            parsed["end_time"] = datetime.fromisoformat(query_params["end_time"])
        except ValueError:
            pass  # Invalid format, use None

    return parsed


@router.get("/query")
@log_function("query_logs")
async def query_logs(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    level: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    format: str = Query("json"),
):
    """Query and retrieve logs based on filters."""
    user_id_var.set(str(current_user.id))

    try:
        query_params = parse_log_query(
            {
                "level": level,
                "start_time": start_time,
                "end_time": end_time,
                "source": source,
                "user_id": user_id,
                "limit": limit,
                "offset": offset,
                "search": search,
                "format": format,
            }
        )

        # Check access
        if not validate_log_access(current_user, query_params["level"]):
            # Log unauthorized attempt
            logger.security_event(
                event="unauthorized_log_access",
                severity="warning",
                properties={
                    "user_id": str(current_user.id),
                    "requested_level": query_params["level"],
                    "ip": get_client_ip(request),
                },
            )

            raise HTTPException(status_code=403, detail="Unauthorized access to logs")

        # Filter logs based on criteria
        filtered_logs = LOG_BUFFER.copy()

        if query_params["level"]:
            filtered_logs = [
                log
                for log in filtered_logs
                if log.get("level") == query_params["level"]
            ]

        if query_params["start_time"]:
            filtered_logs = [
                log
                for log in filtered_logs
                if datetime.fromisoformat(log["timestamp"])
                >= query_params["start_time"]
            ]

        if query_params["end_time"]:
            filtered_logs = [
                log
                for log in filtered_logs
                if datetime.fromisoformat(log["timestamp"]) <= query_params["end_time"]
            ]

        if query_params["search"]:
            pattern = re.compile(query_params["search"], re.IGNORECASE)
            filtered_logs = [
                log for log in filtered_logs if pattern.search(log.get("message", ""))
            ]

        # Apply pagination
        total_count = len(filtered_logs)
        start_idx = query_params["offset"]
        end_idx = start_idx + query_params["limit"]
        paginated_logs = filtered_logs[start_idx:end_idx]

        # No logging for successful queries - too frequent

        return {
            "success": True,
            "logs": paginated_logs,
            "total": total_count,
            "offset": query_params["offset"],
            "limit": query_params["limit"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to query logs",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve logs")


@router.get("/stream")
async def stream_logs(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    level: str = Query("INFO"),
):
    """Stream real-time logs."""
    user_id_var.set(str(current_user.id))

    try:
        level = level.upper()

        if not validate_log_access(current_user, level):
            raise HTTPException(status_code=403, detail="Unauthorized")

        # Only log stream start for debugging/monitoring
        if level in ["ERROR", "CRITICAL"]:
            logger.info(
                "Error log stream started",
                extra={
                    "user_id": str(current_user.id),
                    "level": level,
                },
            )

        def generate():
            """Generate log stream."""
            last_index = 0

            while True:
                # Get new logs
                if last_index < len(LOG_BUFFER):
                    new_logs = LOG_BUFFER[last_index:]
                    last_index = len(LOG_BUFFER)

                    for log in new_logs:
                        if log.get("level") == level or level == "ALL":
                            yield f"data: {json.dumps(log)}\n\n"

                time.sleep(1)  # Poll interval

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to stream logs",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to stream logs")


@router.post("/export")
@log_function("export_logs")
async def export_logs(
    request: Request,
    export_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export logs in various formats."""
    user_id_var.set(str(current_user.id))

    try:
        export_format = export_data.get("format", "json")
        compress = export_data.get("compress", False)
        filters = export_data.get("filters", {})

        # Query logs with filters
        query_params = parse_log_query(filters)

        # Get filtered logs (simplified for demo)
        exported_logs = LOG_BUFFER[: query_params["limit"]]

        # Format logs based on export type
        if export_format == "json":
            output = json.dumps(exported_logs, indent=2)
            content_type = "application/json"
        elif export_format == "csv":
            output = convert_logs_to_csv(exported_logs)
            content_type = "text/csv"
        elif export_format == "text":
            output = convert_logs_to_text(exported_logs)
            content_type = "text/plain"
        else:
            raise HTTPException(status_code=400, detail="Invalid export format")

        # Compress if requested
        if compress:
            output = gzip.compress(output.encode())
            content_type = "application/gzip"

        # Log export for audit trail
        logger.info(
            "Logs exported",
            extra={
                "user_id": str(current_user.id),
                "format": export_format,
                "log_count": len(exported_logs),
                "compressed": compress,
                "ip": get_client_ip(request),
            },
        )

        # Return file
        filename = f'logs_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.{export_format}{".gz" if compress else ""}'

        return Response(
            content=output,
            media_type=content_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to export logs",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to export logs")


@router.get("/stats")
async def get_log_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    range: str = Query("24h"),
):
    """Get log statistics and analytics - cached for performance."""
    user_id_var.set(str(current_user.id))

    try:
        # Check cache first
        if STATS_CACHE["last_update"]:
            cache_age = time.time() - STATS_CACHE["last_update"]
            if cache_age < STATS_CACHE["ttl"] and STATS_CACHE["data"]:
                # Return cached stats without logging
                return {"success": True, "stats": STATS_CACHE["data"]}

        # Calculate time window
        if range == "1h":
            start_time = datetime.utcnow() - timedelta(hours=1)
        elif range == "24h":
            start_time = datetime.utcnow() - timedelta(days=1)
        elif range == "7d":
            start_time = datetime.utcnow() - timedelta(days=7)
        elif range == "30d":
            start_time = datetime.utcnow() - timedelta(days=30)
        else:
            start_time = datetime.utcnow() - timedelta(days=1)

        # Generate statistics
        stats = {
            "total_logs": len(LOG_BUFFER),
            "time_range": range,
            "start_time": start_time.isoformat(),
            "end_time": datetime.utcnow().isoformat(),
            "by_level": {
                "DEBUG": 0,
                "INFO": 0,
                "WARNING": 0,
                "ERROR": 0,
                "CRITICAL": 0,
            },
            "by_source": {},
            "error_rate": 0,
            "top_errors": [],
        }

        # Count logs by level
        for log in LOG_BUFFER:
            level = log.get("level", "INFO")
            if level in stats["by_level"]:
                stats["by_level"][level] += 1

            source = log.get("source", "unknown")
            stats["by_source"][source] = stats["by_source"].get(source, 0) + 1

        # Calculate error rate
        total_logs = len(LOG_BUFFER)
        error_logs = stats["by_level"]["ERROR"] + stats["by_level"]["CRITICAL"]
        if total_logs > 0:
            stats["error_rate"] = round((error_logs / total_logs) * 100, 2)

        # Update cache
        STATS_CACHE["last_update"] = time.time()
        STATS_CACHE["data"] = stats

        # Only log if high error rate detected
        if stats["error_rate"] > 10:
            logger.warning(
                "High error rate detected in logs",
                extra={
                    "error_rate": stats["error_rate"],
                    "error_count": error_logs,
                    "total_logs": total_logs,
                },
            )

        return {"success": True, "stats": stats}

    except Exception as e:
        logger.error(
            "Failed to generate log statistics",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to generate statistics")


@router.delete("/purge")
@log_function("purge_logs")
async def purge_logs(
    request: Request,
    purge_data: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Purge old logs (admin only)."""
    user_id_var.set(str(current_user.id))

    try:
        # TODO: Check admin permission
        # if not is_admin(current_user):
        #     raise HTTPException(status_code=403, detail='Unauthorized')

        older_than_days = purge_data.get("older_than_days", 30)
        level = purge_data.get("level")
        dry_run = purge_data.get("dry_run", True)

        # Calculate cutoff time
        cutoff_time = datetime.utcnow() - timedelta(days=older_than_days)

        # Count logs to be purged
        logs_to_purge = 0
        for log in LOG_BUFFER:
            log_time = datetime.fromisoformat(
                log.get("timestamp", datetime.utcnow().isoformat())
            )
            if log_time < cutoff_time:
                if not level or log.get("level") == level:
                    logs_to_purge += 1

        if not dry_run:
            # Perform actual purge
            original_count = len(LOG_BUFFER)
            LOG_BUFFER[:] = [
                log
                for log in LOG_BUFFER
                if datetime.fromisoformat(
                    log.get("timestamp", datetime.utcnow().isoformat())
                )
                >= cutoff_time
                or (level and log.get("level") != level)
            ]
            actual_purged = original_count - len(LOG_BUFFER)

            # Log purge action for audit trail
            logger.warning(
                "Logs purged",
                extra={
                    "user_id": str(current_user.id),
                    "logs_purged": actual_purged,
                    "older_than_days": older_than_days,
                    "level": level,
                    "ip": get_client_ip(request),
                },
            )

            # Track security event
            app_logger = ApplicationInsightsLogger(db)
            app_logger.track_security_event(
                event_name="logs_purged",
                user_id=str(current_user.id),
                ip_address=get_client_ip(request),
                success=True,
                details={
                    "logs_purged": actual_purged,
                    "older_than_days": older_than_days,
                },
            )

        return {
            "success": True,
            "dry_run": dry_run,
            "logs_to_purge": logs_to_purge,
            "cutoff_time": cutoff_time.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to purge logs",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to purge logs")


@router.get("/recent")
async def get_recent_logs(
    request: Request,
    current_user: User = Depends(get_current_user),
    limit: int = Query(20, le=100),
):
    """Get recent logs quickly without filters."""
    user_id_var.set(str(current_user.id))

    try:
        # Simple recent logs - no filtering, no logging
        recent_logs = LOG_BUFFER[-limit:] if len(LOG_BUFFER) > limit else LOG_BUFFER

        return {
            "success": True,
            "logs": list(reversed(recent_logs)),  # Most recent first
            "count": len(recent_logs),
        }

    except Exception as e:
        logger.error(
            "Failed to get recent logs",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get recent logs")


def convert_logs_to_csv(logs: List[Dict]) -> str:
    """Convert logs to CSV format."""
    output = StringIO()

    if logs:
        writer = csv.DictWriter(output, fieldnames=logs[0].keys())
        writer.writeheader()
        writer.writerows(logs)

    return output.getvalue()


def convert_logs_to_text(logs: List[Dict]) -> str:
    """Convert logs to plain text format."""
    lines = []
    for log in logs:
        line = f"[{log.get('timestamp', 'N/A')}] {log.get('level', 'INFO')}: {log.get('message', '')}"
        lines.append(line)

    return "\n".join(lines)


def add_log_entry(level: str, message: str, **kwargs):
    """Add a log entry to the buffer."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "level": level,
        "message": message,
        **kwargs,
    }

    LOG_BUFFER.append(entry)

    # Maintain buffer size
    if len(LOG_BUFFER) > MAX_LOG_BUFFER:
        LOG_BUFFER.pop(0)
