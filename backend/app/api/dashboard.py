# app/api/dashboard.py - Dashboard overview endpoints with optimized logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import time

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.logging import get_logger, log_function
from app.logging.core import request_id_var, user_id_var

logger = get_logger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DashboardStats(BaseModel):
    campaigns: Dict[str, Any]
    submissions: Dict[str, Any]
    recent_activity: List[Dict[str, Any]]
    performance_metrics: Dict[str, Any]


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


@router.get("/overview", response_model=DashboardStats)
@log_function("get_dashboard_overview")
def get_dashboard_overview(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get dashboard overview with key metrics - optimized queries"""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    try:
        start_time = time.perf_counter()

        # Campaign statistics - single optimized query
        campaigns_query = text(
            """
            SELECT 
                COUNT(*) as total_campaigns,
                COUNT(CASE WHEN status IN ('ACTIVE', 'PROCESSING') THEN 1 END) as active_campaigns,
                COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as completed_campaigns,
                COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_campaigns,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '7 days' THEN 1 END) as campaigns_this_week,
                COUNT(CASE WHEN created_at >= NOW() - INTERVAL '30 days' THEN 1 END) as campaigns_this_month
            FROM campaigns WHERE user_id = :user_id
        """
        )

        campaigns_result = (
            db.execute(campaigns_query, {"user_id": user_id}).mappings().first()
        )
        campaigns_stats = dict(campaigns_result) if campaigns_result else {}

        # Submission statistics - single optimized query
        submissions_query = text(
            """
            SELECT 
                COUNT(s.id) as total_submissions,
                COUNT(CASE WHEN s.success = true THEN 1 END) as successful_submissions,
                COUNT(CASE WHEN s.success = false THEN 1 END) as failed_submissions,
                COUNT(CASE WHEN s.status = 'pending' THEN 1 END) as pending_submissions,
                COUNT(CASE WHEN s.captcha_encountered = true THEN 1 END) as captcha_submissions,
                COUNT(CASE WHEN s.created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as submissions_today,
                COUNT(CASE WHEN s.created_at >= NOW() - INTERVAL '7 days' THEN 1 END) as submissions_this_week
            FROM submissions s
            JOIN campaigns c ON s.campaign_id = c.id
            WHERE c.user_id = :user_id
        """
        )

        submissions_result = (
            db.execute(submissions_query, {"user_id": user_id}).mappings().first()
        )
        submissions_stats = dict(submissions_result) if submissions_result else {}

        # Calculate success rate
        total_subs = submissions_stats.get("total_submissions", 0)
        successful_subs = submissions_stats.get("successful_submissions", 0)
        success_rate = (successful_subs / total_subs * 100) if total_subs > 0 else 0

        # Recent activity - limited to 10 items
        recent_activity_query = text(
            """
            SELECT * FROM (
                SELECT 
                    'campaign' as type,
                    c.name as title,
                    c.status as status,
                    c.created_at as timestamp,
                    c.id as entity_id
                FROM campaigns c
                WHERE c.user_id = :user_id
                ORDER BY c.created_at DESC
                LIMIT 5
            ) campaigns
            
            UNION ALL
            
            SELECT * FROM (
                SELECT 
                    'submission' as type,
                    CONCAT('Submission to ', COALESCE(w.domain, 'unknown')) as title,
                    s.status as status,
                    s.created_at as timestamp,
                    s.id as entity_id
                FROM submissions s
                JOIN campaigns c ON s.campaign_id = c.id
                LEFT JOIN websites w ON s.website_id = w.id
                WHERE c.user_id = :user_id
                ORDER BY s.created_at DESC
                LIMIT 5
            ) submissions
            
            ORDER BY timestamp DESC
            LIMIT 10
        """
        )

        recent_activity_result = (
            db.execute(recent_activity_query, {"user_id": user_id}).mappings().all()
        )

        recent_activity = []
        for activity in recent_activity_result:
            activity_dict = dict(activity)
            if activity_dict.get("timestamp"):
                activity_dict["timestamp"] = activity_dict["timestamp"].isoformat()
            recent_activity.append(activity_dict)

        # Performance metrics
        performance_metrics = {
            "success_rate": round(success_rate, 2),
            "avg_submissions_per_campaign": round(
                submissions_stats.get("total_submissions", 0)
                / max(campaigns_stats.get("total_campaigns", 1), 1),
                2,
            ),
            "captcha_encounter_rate": round(
                (submissions_stats.get("captcha_submissions", 0) / max(total_subs, 1))
                * 100,
                2,
            ),
            "active_campaign_ratio": round(
                (
                    campaigns_stats.get("active_campaigns", 0)
                    / max(campaigns_stats.get("total_campaigns", 1), 1)
                )
                * 100,
                2,
            ),
        }

        query_time = (time.perf_counter() - start_time) * 1000

        # Only log if queries are slow or user has significant data
        if query_time > 100 or campaigns_stats.get("total_campaigns", 0) > 50:
            logger.database_operation(
                operation="DASHBOARD_OVERVIEW",
                table="multiple",
                duration_ms=query_time,
                rows_affected=len(recent_activity),
                properties={
                    "total_campaigns": campaigns_stats.get("total_campaigns", 0),
                    "total_submissions": total_subs,
                    "success_rate": success_rate,
                },
            )

        return DashboardStats(
            campaigns=campaigns_stats,
            submissions=submissions_stats,
            recent_activity=recent_activity,
            performance_metrics=performance_metrics,
        )

    except Exception as e:
        logger.error(
            "Failed to retrieve dashboard data",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": user_id,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve dashboard data")


@router.get("/quick-stats")
@log_function("get_quick_stats")
def get_quick_stats(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Get quick stats for the top navigation bar - cached/lightweight"""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    try:
        # Quick stats query - optimized with single scan
        stats_query = text(
            """
            SELECT 
                (SELECT COUNT(*) FROM campaigns WHERE user_id = :user_id AND status IN ('ACTIVE', 'PROCESSING')) as active_campaigns,
                (SELECT COUNT(*) FROM submissions s JOIN campaigns c ON s.campaign_id = c.id WHERE c.user_id = :user_id AND s.status = 'pending') as pending_submissions,
                (SELECT COUNT(*) FROM submissions s JOIN campaigns c ON s.campaign_id = c.id WHERE c.user_id = :user_id AND s.created_at >= NOW() - INTERVAL '24 hours') as todays_submissions
        """
        )

        result = db.execute(stats_query, {"user_id": user_id}).mappings().first()

        # No logging for quick stats - this is called frequently
        # Only log errors, not successful fetches

        return (
            dict(result)
            if result
            else {
                "active_campaigns": 0,
                "pending_submissions": 0,
                "todays_submissions": 0,
            }
        )

    except Exception as e:
        # Only log actual errors, not routine operations
        logger.error(
            "Failed to retrieve quick stats",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": user_id,
            },
            exc_info=True,
        )
        # Return default values on error - don't break the UI
        return {
            "active_campaigns": 0,
            "pending_submissions": 0,
            "todays_submissions": 0,
        }


@router.get("/recent-campaigns")
@log_function("get_recent_campaigns")
def get_recent_campaigns(
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get recent campaigns for quick access - lightweight query"""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    try:
        campaigns_query = text(
            """
            SELECT 
                id, name, status, total_urls, successful, failed,
                CASE 
                    WHEN total_urls > 0 
                    THEN ROUND((successful * 100.0 / total_urls), 1)
                    ELSE 0 
                END as success_rate,
                created_at, updated_at
            FROM campaigns 
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            LIMIT :limit
        """
        )

        result = (
            db.execute(campaigns_query, {"user_id": user_id, "limit": limit})
            .mappings()
            .all()
        )

        campaigns = []
        for campaign in result:
            campaign_dict = dict(campaign)
            # Convert dates to ISO strings
            for field in ["created_at", "updated_at"]:
                if campaign_dict.get(field):
                    campaign_dict[field] = campaign_dict[field].isoformat()
            campaigns.append(campaign_dict)

        # No logging for successful routine operations
        # The @log_function decorator handles timing/errors

        return {"campaigns": campaigns, "count": len(campaigns)}

    except Exception as e:
        logger.error(
            "Failed to retrieve recent campaigns",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": user_id,
                "limit": limit,
            },
            exc_info=True,
        )
        return {"campaigns": [], "count": 0}


@router.get("/performance-trends")
@log_function("get_performance_trends")
def get_performance_trends(
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get performance trends over time - for charts/graphs"""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    if days > 30:
        days = 30  # Limit to prevent expensive queries

    try:
        trends_query = text(
            """
            WITH daily_stats AS (
                SELECT 
                    DATE(s.created_at) as date,
                    COUNT(s.id) as submissions,
                    COUNT(CASE WHEN s.success = true THEN 1 END) as successful,
                    COUNT(CASE WHEN s.success = false THEN 1 END) as failed
                FROM submissions s
                JOIN campaigns c ON s.campaign_id = c.id
                WHERE c.user_id = :user_id
                    AND s.created_at >= CURRENT_DATE - INTERVAL :days DAY
                GROUP BY DATE(s.created_at)
                ORDER BY date DESC
            )
            SELECT 
                date,
                submissions,
                successful,
                failed,
                CASE 
                    WHEN submissions > 0 
                    THEN ROUND((successful * 100.0 / submissions), 1)
                    ELSE 0 
                END as success_rate
            FROM daily_stats
        """
        )

        start_time = time.perf_counter()
        result = (
            db.execute(trends_query, {"user_id": user_id, "days": days})
            .mappings()
            .all()
        )
        query_time = (time.perf_counter() - start_time) * 1000

        trends = []
        for row in result:
            trend_dict = dict(row)
            if trend_dict.get("date"):
                trend_dict["date"] = trend_dict["date"].isoformat()
            trends.append(trend_dict)

        # Only log slow queries
        if query_time > 200:
            logger.performance_metric(
                metric="slow_trends_query",
                value=query_time,
                unit="ms",
                properties={
                    "days": days,
                    "rows": len(trends),
                },
            )

        return {
            "trends": trends,
            "days": days,
            "data_points": len(trends),
        }

    except Exception as e:
        logger.error(
            "Failed to retrieve performance trends",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": user_id,
                "days": days,
            },
            exc_info=True,
        )
        return {
            "trends": [],
            "days": days,
            "data_points": 0,
        }
