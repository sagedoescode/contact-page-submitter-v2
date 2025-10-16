# app/api/activity.py - Optimized with focused logging
from __future__ import annotations

import time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi.responses import StreamingResponse
import csv
import io
import datetime as dt

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_admin_user
from app.models.user import User

from app.logging import get_logger, log_function, log_exceptions
from app.logging.core import user_id_var

router = APIRouter(prefix="/api/activity", tags=["activity"], redirect_slashes=False)
logger = get_logger(__name__)


def get_client_ip(request: Request) -> str:
    """Extract client IP from request"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


@log_exceptions("resolve_target_user")
def _resolve_target_user_id(
    db: Session,
    current_user: User,
    user_id: Optional[str],
) -> str:
    """Resolve target user ID with admin check"""
    target_user_id = str(current_user.id)

    if user_id and user_id != target_user_id:
        # Admin check
        get_admin_user(db=db, current_user=current_user)

        logger.auth_event(
            action="admin_view_activity",
            email=current_user.email,
            success=True,
            ip_address=get_client_ip(None),
        )

        target_user_id = user_id

    return target_user_id


def _build_filters(
    target_user_id: str,
    *,
    source: Optional[str],
    level: Optional[str],
    action: Optional[str],
    status: Optional[str],
    q: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
) -> tuple[str, Dict[str, Any]]:
    """Build SQL filters for activity queries"""
    where_parts = ["user_id = :uid"]
    params: Dict[str, Any] = {"uid": target_user_id}

    if date_from:
        where_parts.append("timestamp >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where_parts.append("timestamp < :date_to")
        params["date_to"] = date_to
    if q:
        where_parts.append(
            "(COALESCE(message,'') ILIKE :q OR COALESCE(details,'') ILIKE :q)"
        )
        params["q"] = f"%{q}%"
    if action:
        where_parts.append("COALESCE(action,'') ILIKE :action")
        params["action"] = f"%{action}%"
    if status:
        where_parts.append("COALESCE(status,'') ILIKE :status")
        params["status"] = f"%{status}%"

    where_clause = " AND ".join(where_parts) if where_parts else "TRUE"

    app_level_filter = ""
    if level:
        app_level_filter = "AND level = :level"
        params["level"] = level

    base_sql = f"""
        WITH merged AS (
            SELECT
                'system'::text AS source,
                id::text       AS id,
                user_id::text  AS user_id,
                action         AS title,
                details        AS details,
                NULL::text     AS message,
                NULL::jsonb    AS context,
                NULL::text     AS target_url,
                action         AS action,
                NULL::text     AS status,
                timestamp      AS timestamp
            FROM system_logs
            WHERE {where_clause}

            UNION ALL

            SELECT
                'app'::text    AS source,
                id::text       AS id,
                user_id::text  AS user_id,
                level          AS title,
                NULL::text     AS details,
                message        AS message,
                COALESCE(context, '{{}}'::jsonb) AS context,
                NULL::text     AS target_url,
                NULL::text     AS action,
                NULL::text     AS status,
                timestamp      AS timestamp
            FROM logs
            WHERE {where_clause}
            {app_level_filter}

            UNION ALL

            SELECT
                'submission'::text AS source,
                id::text           AS id,
                user_id::text      AS user_id,
                action             AS title,
                details            AS details,
                NULL::text         AS message,
                NULL::jsonb        AS context,
                COALESCE(target_url,'') AS target_url,
                action             AS action,
                COALESCE(status,'') AS status,
                timestamp          AS timestamp
            FROM submission_logs
            WHERE {where_clause}
        )
        SELECT * FROM merged
    """

    if source in ("system", "app", "submission"):
        base_sql = f"SELECT * FROM ({base_sql}) AS x WHERE source = :source"
        params["source"] = source

    return base_sql, params


@router.get("/stream")
@log_function("get_activity_stream")
def activity_stream(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    me: bool = Query(True, description="Limit to my own activity"),
    user_id: Optional[str] = Query(
        None, description="Admin: view a specific user's activity"
    ),
    source: Optional[str] = Query(None, pattern="^(system|app|submission)$"),
    level: Optional[str] = Query(None, pattern="^(INFO|WARN|ERROR)$"),
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Full-text search"),
    date_from: Optional[str] = Query(None, description="ISO timestamp (inclusive)"),
    date_to: Optional[str] = Query(None, description="ISO timestamp (exclusive)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    """Get activity stream with filtering and pagination"""
    user_id_var.set(str(current_user.id))

    try:
        target_user_id = (
            str(current_user.id)
            if me
            else _resolve_target_user_id(db, current_user, user_id)
        )

        query_start = time.time()
        base_sql, params = _build_filters(
            target_user_id,
            source=source,
            level=level,
            action=action,
            status=status,
            q=q,
            date_from=date_from,
            date_to=date_to,
        )

        # Count query
        count_sql = f"SELECT COUNT(*)::int FROM ({base_sql}) AS c"
        total = db.execute(text(count_sql), params).scalar() or 0

        # Page query
        page_sql = f"{base_sql} ORDER BY timestamp DESC LIMIT :limit OFFSET :offset"
        params.update({"limit": page_size, "offset": (page - 1) * page_size})
        rows = db.execute(text(page_sql), params).mappings().all()

        query_time = (time.time() - query_start) * 1000

        logger.database_operation(
            operation="SELECT",
            table="activity_logs",
            duration_ms=query_time,
            affected_rows=len(rows),
            success=True,
            page=page,
            page_size=page_size,
            total=total,
        )

        return {
            "items": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "pages": (total + page_size - 1) // page_size,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(
            e,
            handled=False,
            context={"endpoint": "/activity/stream"},
        )
        raise HTTPException(status_code=500, detail="Failed to fetch activity")


@router.get("/export")
@log_function("export_activity_csv")
def export_activity_csv(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    me: bool = Query(True, description="Limit to my own activity"),
    user_id: Optional[str] = Query(
        None, description="Admin: view a specific user's activity"
    ),
    source: Optional[str] = Query(None, pattern="^(system|app|submission)$"),
    level: Optional[str] = Query(None, pattern="^(INFO|WARN|ERROR)$"),
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Export activity to CSV file"""
    user_id_var.set(str(current_user.id))

    try:
        target_user_id = (
            str(current_user.id)
            if me
            else _resolve_target_user_id(db, current_user, user_id)
        )

        export_start = time.time()
        base_sql, params = _build_filters(
            target_user_id,
            source=source,
            level=level,
            action=action,
            status=status,
            q=q,
            date_from=date_from,
            date_to=date_to,
        )
        export_sql = f"{base_sql} ORDER BY timestamp DESC"

        rows = db.execute(text(export_sql), params).mappings().all()
        export_query_time = (time.time() - export_start) * 1000

        logger.database_operation(
            operation="SELECT",
            table="activity_logs",
            duration_ms=export_query_time,
            affected_rows=len(rows),
            success=True,
        )

        # Build CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "source",
                "id",
                "user_id",
                "title",
                "message",
                "details",
                "action",
                "status",
                "target_url",
                "timestamp",
            ]
        )

        for r in rows:
            writer.writerow(
                [
                    r.get("source", ""),
                    r.get("id", ""),
                    r.get("user_id", ""),
                    r.get("title", ""),
                    r.get("message", ""),
                    r.get("details", ""),
                    r.get("action", ""),
                    r.get("status", ""),
                    r.get("target_url", ""),
                    r.get("timestamp", ""),
                ]
            )

        output.seek(0)
        filename = f"activity_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}Z.csv"
        file_size = len(output.getvalue())

        logger.performance_metric(
            name="activity_export",
            value=file_size,
            unit="bytes",
            row_count=len(rows),
        )

        return StreamingResponse(
            io.StringIO(output.getvalue()),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except Exception as e:
        db.rollback()
        logger.exception(
            e,
            handled=False,
            context={"endpoint": "/activity/export"},
        )
        raise HTTPException(status_code=500, detail="Failed to export activity")


@router.get("/stats")
@log_function("get_activity_stats")
def activity_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    me: bool = Query(True, description="Limit to my own activity"),
    user_id: Optional[str] = Query(
        None, description="Admin: view a specific user's activity"
    ),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Get activity statistics"""
    user_id_var.set(str(current_user.id))

    target_user_id = (
        str(current_user.id)
        if me
        else _resolve_target_user_id(db, current_user, user_id)
    )

    try:
        parts = ["user_id = :uid"]
        params: Dict[str, Any] = {"uid": target_user_id}
        if date_from:
            parts.append("timestamp >= :date_from")
            params["date_from"] = date_from
        if date_to:
            parts.append("timestamp < :date_to")
            params["date_to"] = date_to
        where = " AND ".join(parts)

        stats_start = time.time()

        sql_by_source = f"""
          SELECT 'system' AS source, COUNT(*)::int AS cnt FROM system_logs WHERE {where}
          UNION ALL
          SELECT 'app' AS source, COUNT(*)::int AS cnt FROM logs WHERE {where}
          UNION ALL
          SELECT 'submission' AS source, COUNT(*)::int AS cnt FROM submission_logs WHERE {where}
        """

        sql_by_level = f"""
          SELECT COALESCE(level,'INFO') AS level, COUNT(*)::int AS cnt
          FROM logs
          WHERE {where}
          GROUP BY level
        """

        by_source = {
            r["source"]: r["cnt"]
            for r in db.execute(text(sql_by_source), params).mappings()
        }
        by_level = {
            r["level"]: r["cnt"]
            for r in db.execute(text(sql_by_level), params).mappings()
        }

        stats_time = (time.time() - stats_start) * 1000

        logger.database_operation(
            operation="AGGREGATE",
            table="logs",
            duration_ms=stats_time,
            success=True,
        )

        stats_data = {
            "by_source": {
                "system": by_source.get("system", 0),
                "app": by_source.get("app", 0),
                "submission": by_source.get("submission", 0),
            },
            "by_level": {
                "INFO": by_level.get("INFO", 0),
                "WARN": by_level.get("WARN", 0),
                "ERROR": by_level.get("ERROR", 0),
            },
        }

        return stats_data

    except Exception as e:
        db.rollback()
        logger.exception(
            e,
            handled=True,
            context={"endpoint": "/activity/stats"},
        )
        return {
            "by_source": {"system": 0, "app": 0, "submission": 0},
            "by_level": {"INFO": 0, "WARN": 0, "ERROR": 0},
        }
