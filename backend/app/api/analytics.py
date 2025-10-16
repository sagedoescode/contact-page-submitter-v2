# app/api/analytics.py - Fixed version without Request parameters
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User

from app.logging import get_logger, log_function, log_exceptions
from app.logging.core import user_id_var

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
logger = get_logger(__name__)


@router.get("/user")
@log_function("get_user_analytics")
async def analytics_user(
    include_detailed: bool = Query(False),
    days: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get comprehensive user analytics summary"""
    user_id_var.set(str(current_user.id))

    try:
        total_start = time.time()

        # Test database connection
        try:
            db.execute(text("SELECT 1")).fetchone()
        except Exception as db_error:
            logger.exception(db_error, handled=True)
            raise HTTPException(status_code=503, detail="Database connection failed")

        # Build date filter
        date_filter = ""
        if days:
            if days == 1:
                date_filter = " AND DATE(created_at) = CURRENT_DATE"
            else:
                date_filter = (
                    f" AND created_at >= CURRENT_DATE - INTERVAL '{days} days'"
                )

        # Get campaign stats
        campaigns_query = text(
            f"""
            SELECT 
                COUNT(*)::int as total_campaigns,
                COUNT(CASE WHEN status IN ('ACTIVE', 'running', 'PROCESSING') THEN 1 END)::int as active_campaigns,
                COUNT(CASE WHEN status IN ('COMPLETED', 'completed') THEN 1 END)::int as completed_campaigns,
                COALESCE(SUM(total_urls), 0)::int as total_urls,
                COALESCE(SUM(submitted_count), 0)::int as submitted_count,
                COALESCE(SUM(successful), 0)::int as successful,
                COALESCE(SUM(failed), 0)::int as failed,
                COALESCE(SUM(processed), 0)::int as processed
            FROM campaigns 
            WHERE user_id = :uid{date_filter}
        """
        )

        campaign_stats = (
            db.execute(campaigns_query, {"uid": str(current_user.id)})
            .mappings()
            .first()
        ) or {}

        # Get submission stats
        submissions_query = text(
            f"""
            SELECT 
                COUNT(*)::int as total_submissions,
                COUNT(CASE WHEN success = true THEN 1 END)::int as successful_submissions,
                COUNT(CASE WHEN success = false THEN 1 END)::int as failed_submissions,
                COUNT(CASE WHEN captcha_encountered = true THEN 1 END)::int as captcha_submissions,
                COUNT(CASE WHEN captcha_solved = true THEN 1 END)::int as captcha_solved,
                COALESCE(AVG(retry_count), 0)::float as avg_retry_count,
                COUNT(CASE WHEN email_extracted IS NOT NULL THEN 1 END)::int as emails_extracted
            FROM submissions 
            WHERE user_id = :uid{date_filter}
        """
        )

        submission_stats = (
            db.execute(submissions_query, {"uid": str(current_user.id)})
            .mappings()
            .first()
        ) or {}

        # Get website count
        website_stats = (
            db.execute(
                text(
                    "SELECT COUNT(*)::int as websites_count FROM websites WHERE user_id = :uid"
                ),
                {"uid": str(current_user.id)},
            )
            .mappings()
            .first()
        ) or {}

        total_campaigns = int(campaign_stats.get("total_campaigns", 0) or 0)
        total_submissions = int(submission_stats.get("total_submissions", 0) or 0)
        successful_submissions = int(
            submission_stats.get("successful_submissions", 0) or 0
        )

        # Calculate rates
        success_rate = (
            (successful_submissions / total_submissions * 100)
            if total_submissions > 0
            else 0
        )

        captcha_encounter_rate = (
            (
                int(submission_stats.get("captcha_submissions", 0) or 0)
                / total_submissions
                * 100
            )
            if total_submissions > 0
            else 0
        )

        captcha_total = int(submission_stats.get("captcha_submissions", 0) or 0)
        captcha_success_rate = 0
        if captcha_total > 0:
            captcha_success_rate = (
                int(submission_stats.get("captcha_solved", 0) or 0)
                / captcha_total
                * 100
            )

        # Get recent activity if detailed
        recent_activity = {}
        if include_detailed:
            try:
                recent_date_filter = (
                    date_filter
                    if days and days <= 7
                    else " AND created_at >= NOW() - INTERVAL '7 days'"
                )
                recent_query = text(
                    f"""
                    SELECT 
                        status,
                        COUNT(*) as count,
                        MAX(created_at) as last_activity
                    FROM submissions 
                    WHERE user_id = :uid{recent_date_filter}
                    GROUP BY status
                    ORDER BY count DESC
                """
                )
                recent_results = (
                    db.execute(recent_query, {"uid": str(current_user.id)})
                    .mappings()
                    .all()
                )

                recent_activity = {
                    "recent_submissions_by_status": [
                        {
                            "status": row["status"],
                            "count": int(row["count"]),
                            "last_activity": (
                                row["last_activity"].isoformat()
                                if row["last_activity"]
                                else None
                            ),
                        }
                        for row in recent_results
                    ]
                }
            except Exception as e:
                logger.warning(
                    "Failed to fetch recent activity",
                    context={"error": str(e)[:100]},
                )
                recent_activity = {"recent_submissions_by_status": []}

        total_time = (time.time() - total_start) * 1000

        logger.database_operation(
            operation="SELECT",
            table="campaigns,submissions,websites",
            duration_ms=total_time,
            success=True,
            has_campaigns=total_campaigns > 0,
            has_submissions=total_submissions > 0,
        )

        payload = {
            "user_id": str(current_user.id),
            "email": current_user.email,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "campaigns_count": total_campaigns,
            "websites_count": int(website_stats.get("websites_count", 0) or 0),
            "active_campaigns": int(campaign_stats.get("active_campaigns", 0) or 0),
            "total_submissions": total_submissions,
            "successful_submissions": successful_submissions,
            "failed_submissions": int(
                submission_stats.get("failed_submissions", 0) or 0
            ),
            "captcha_submissions": int(
                submission_stats.get("captcha_submissions", 0) or 0
            ),
            "captcha_solved": int(submission_stats.get("captcha_solved", 0) or 0),
            "emails_extracted": int(submission_stats.get("emails_extracted", 0) or 0),
            "avg_retry_count": round(
                float(submission_stats.get("avg_retry_count", 0) or 0), 2
            ),
            "success_rate": round(success_rate, 2),
            "captcha_encounter_rate": round(captcha_encounter_rate, 2),
            "captcha_success_rate": round(captcha_success_rate, 2),
        }

        if include_detailed:
            payload["recent_activity"] = recent_activity

        return payload

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            e,
            handled=True,
            context={"endpoint": "/analytics/user"},
        )
        return {
            "user_id": str(current_user.id),
            "email": current_user.email,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "campaigns_count": 0,
            "total_submissions": 0,
            "successful_submissions": 0,
            "success_rate": 0,
            "error": True,
        }


@router.get("/daily-stats")
@log_function("get_daily_analytics_stats")
async def analytics_daily_stats(
    days: int = Query(30, ge=1, le=365),
    campaign_id: Optional[str] = Query(None),
    include_trends: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get daily submission statistics"""
    user_id_var.set(str(current_user.id))

    try:
        stats_start = time.time()
        params = {"uid": str(current_user.id)}

        # Build where clause
        if days == 1:
            where_clause = "s.user_id = :uid AND DATE(s.created_at) = CURRENT_DATE"
        elif days == 7:
            where_clause = (
                "s.user_id = :uid AND s.created_at >= CURRENT_DATE - INTERVAL '7 days'"
            )
        elif days == 30:
            where_clause = (
                "s.user_id = :uid AND s.created_at >= CURRENT_DATE - INTERVAL '30 days'"
            )
        else:
            where_clause = f"s.user_id = :uid AND s.created_at >= CURRENT_DATE - INTERVAL '{days} days'"

        if campaign_id:
            where_clause += " AND s.campaign_id = :campaign_id"
            params["campaign_id"] = campaign_id

        daily_query = text(
            f"""
            SELECT
                CAST(date_trunc('day', s.created_at) AS date) AS day,
                COUNT(*)::int AS total,
                SUM(CASE WHEN s.success = true THEN 1 ELSE 0 END)::int AS success,
                SUM(CASE WHEN s.success = false THEN 1 ELSE 0 END)::int AS failed,
                SUM(CASE WHEN s.captcha_encountered = true THEN 1 ELSE 0 END)::int AS captcha_encountered,
                SUM(CASE WHEN s.captcha_solved = true THEN 1 ELSE 0 END)::int AS captcha_solved,
                COALESCE(AVG(s.retry_count), 0)::numeric(10,2) AS avg_retries
            FROM submissions s
            WHERE {where_clause}
            GROUP BY 1
            ORDER BY 1 ASC
        """
        )

        rows = (db.execute(daily_query, params).mappings().all()) or []

        data = []
        for r in rows:
            day_data = {
                "day": (
                    r["day"].isoformat()
                    if hasattr(r["day"], "isoformat")
                    else str(r["day"])
                ),
                "total": int(r.get("total", 0) or 0),
                "success": int(r.get("success", 0) or 0),
                "failed": int(r.get("failed", 0) or 0),
                "captcha_encountered": int(r.get("captcha_encountered", 0) or 0),
                "captcha_solved": int(r.get("captcha_solved", 0) or 0),
                "avg_retries": float(r.get("avg_retries", 0) or 0),
                "success_rate": 0,
            }

            if day_data["total"] > 0:
                day_data["success_rate"] = round(
                    (day_data["success"] / day_data["total"]) * 100, 2
                )

            data.append(day_data)

        # Add empty day for single day with no data
        if days == 1 and len(data) == 0:
            data = [
                {
                    "day": datetime.now().date().isoformat(),
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                    "captcha_encountered": 0,
                    "captcha_solved": 0,
                    "avg_retries": 0,
                    "success_rate": 0,
                }
            ]

        total_submissions = sum(d["total"] for d in data)
        total_success = sum(d["success"] for d in data)
        overall_success_rate = (
            (total_success / total_submissions * 100) if total_submissions > 0 else 0
        )

        stats_time = (time.time() - stats_start) * 1000

        logger.database_operation(
            operation="SELECT",
            table="submissions",
            duration_ms=stats_time,
            affected_rows=len(data),
            success=True,
            days=days,
            campaign_filtered=campaign_id is not None,
        )

        return {
            "days": days,
            "campaign_filter": campaign_id,
            "series": data,
            "summary": {
                "total_submissions": total_submissions,
                "total_success": total_success,
                "total_failed": sum(d["failed"] for d in data),
                "overall_success_rate": round(overall_success_rate, 2),
                "avg_daily_submissions": round(
                    total_submissions / max(len(data), 1), 2
                ),
                "active_days": len([d for d in data if d["total"] > 0]),
                "data_points": len(data),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.exception(
            e,
            handled=True,
            context={"endpoint": "/analytics/daily-stats", "days": days},
        )
        return {
            "days": days,
            "campaign_filter": campaign_id,
            "series": [],
            "summary": {
                "total_submissions": 0,
                "total_success": 0,
                "overall_success_rate": 0,
                "data_points": 0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/performance")
@log_function("get_performance_analytics")
async def analytics_performance(
    limit: int = Query(10, ge=1, le=50),
    time_range: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get performance analytics for campaigns"""
    user_id_var.set(str(current_user.id))

    try:
        perf_start = time.time()

        campaign_query = text(
            """
            SELECT 
                c.id,
                c.name,
                c.status,
                COALESCE(c.total_urls, 0) as total_urls,
                COALESCE(c.total_websites, 0) as total_websites,
                COALESCE(c.processed, 0) as processed,
                COALESCE(c.successful, 0) as successful,
                COALESCE(c.failed, 0) as failed,
                CASE 
                    WHEN COALESCE(c.total_websites, 0) > 0 
                    THEN ROUND(CAST((COALESCE(c.processed, 0)::float / c.total_websites) * 100 AS numeric), 2)
                    ELSE 0 
                END as processing_rate,
                CASE 
                    WHEN COALESCE(c.processed, 0) > 0 
                    THEN ROUND(CAST((COALESCE(c.successful, 0)::float / c.processed) * 100 AS numeric), 2)
                    ELSE 0 
                END as success_rate,
                c.created_at
            FROM campaigns c
            WHERE c.user_id = :uid
            AND c.created_at >= NOW() - make_interval(days => :time_range)
            ORDER BY c.created_at DESC
            LIMIT :limit
        """
        )

        campaigns = (
            db.execute(
                campaign_query,
                {
                    "uid": str(current_user.id),
                    "time_range": time_range,
                    "limit": limit,
                },
            )
            .mappings()
            .all()
        ) or []

        summary_query = text(
            """
            SELECT
                COUNT(DISTINCT c.id) as total_campaigns,
                COUNT(DISTINCT CASE WHEN c.status IN ('running', 'ACTIVE') THEN c.id END) as active_campaigns,
                ROUND(CAST(AVG(
                    CASE WHEN COALESCE(c.successful, 0) > 0 AND COALESCE(c.processed, 0) > 0 
                    THEN (COALESCE(c.successful, 0)::float / COALESCE(c.processed, 1)) * 100 
                    END
                ) AS numeric), 2) as avg_campaign_success_rate
            FROM campaigns c
            WHERE c.user_id = :uid
            AND c.created_at >= NOW() - make_interval(days => :time_range)
        """
        )

        summary_row = (
            db.execute(
                summary_query,
                {"uid": str(current_user.id), "time_range": time_range},
            )
            .mappings()
            .first()
        ) or {}

        perf_time = (time.time() - perf_start) * 1000

        logger.database_operation(
            operation="SELECT",
            table="campaigns",
            duration_ms=perf_time,
            affected_rows=len(campaigns),
            success=True,
            time_range=time_range,
        )

        return {
            "time_range_days": time_range,
            "limit": limit,
            "campaigns": [
                {
                    "id": str(c["id"]),
                    "name": c["name"] or "Untitled Campaign",
                    "status": c["status"] or "unknown",
                    "total_urls": int(c.get("total_urls", 0) or 0),
                    "total_websites": int(c.get("total_websites", 0) or 0),
                    "processed": int(c.get("processed", 0) or 0),
                    "successful": int(c.get("successful", 0) or 0),
                    "failed": int(c.get("failed", 0) or 0),
                    "processing_rate": float(c.get("processing_rate", 0) or 0),
                    "success_rate": float(c.get("success_rate", 0) or 0),
                    "created_at": (
                        c["created_at"].isoformat() if c["created_at"] else None
                    ),
                }
                for c in campaigns
            ],
            "summary": {
                "total_campaigns": int(summary_row.get("total_campaigns", 0) or 0),
                "active_campaigns": int(summary_row.get("active_campaigns", 0) or 0),
                "avg_campaign_success_rate": round(
                    float(summary_row.get("avg_campaign_success_rate", 0) or 0), 2
                ),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.exception(
            e,
            handled=True,
            context={"endpoint": "/analytics/performance", "time_range": time_range},
        )
        return {
            "time_range_days": time_range,
            "limit": limit,
            "campaigns": [],
            "summary": {
                "total_campaigns": 0,
                "active_campaigns": 0,
                "avg_campaign_success_rate": 0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/revenue")
@log_function("get_revenue_analytics")
async def get_revenue_analytics(
    days: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get revenue analytics based on successful submissions"""
    user_id_var.set(str(current_user.id))

    try:
        revenue_start = time.time()
        price_per_submission = 0.50

        # Build date filter
        date_filter = ""
        if days:
            if days == 1:
                date_filter = " AND DATE(created_at) = CURRENT_DATE"
            else:
                date_filter = (
                    f" AND created_at >= CURRENT_DATE - INTERVAL '{days} days'"
                )

        # Get revenue stats
        revenue_query = text(
            f"""
            SELECT 
                COUNT(CASE WHEN success = true THEN 1 END) as successful_submissions
            FROM submissions 
            WHERE user_id = :uid{date_filter}
        """
        )

        result = (
            db.execute(revenue_query, {"uid": str(current_user.id)}).mappings().first()
        )
        successful_count = result["successful_submissions"] or 0

        total_revenue = successful_count * price_per_submission

        revenue_time = (time.time() - revenue_start) * 1000

        logger.database_operation(
            operation="SELECT",
            table="submissions",
            duration_ms=revenue_time,
            success=True,
            successful_submissions=successful_count,
            total_revenue=total_revenue,
        )

        return {
            "price_per_submission": price_per_submission,
            "total_revenue": total_revenue,
            "successful_submissions": successful_count,
        }

    except Exception as e:
        logger.exception(
            e,
            handled=True,
            context={"endpoint": "/analytics/revenue", "days": days},
        )
        return {
            "price_per_submission": 0.50,
            "total_revenue": 0,
            "successful_submissions": 0,
        }
