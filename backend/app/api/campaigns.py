# app/api/campaigns.py - Complete Working Version
import time
import uuid
import csv
import io
import os
import sys
import traceback
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Request,
    Query,
    Form,
    File,
    UploadFile,
)
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.log_service import LogService as ApplicationInsightsLogger
from app.services.submission_service import SubmissionService
from app.services.csv_parser_service import CSVParserService
from app.logging import get_logger, log_function, log_exceptions
from app.logging.core import request_id_var, user_id_var, campaign_id_var
from app.models.campaign import CampaignStatus
from app.schemas.campaign import (
    CampaignActionRequest,
    CampaignActionResponse,
)
from app.workers.processors.subprocess_runner import (
    start_campaign_processing,
    stop_processor,
)

# Initialize structured logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"], redirect_slashes=False)


def get_user_profile_for_campaign(db: Session, user_id: UUID) -> Dict[str, Any]:
    """Fetch comprehensive user profile data for campaign form filling."""
    try:
        query = text("""
            SELECT 
                u.first_name, u.last_name, u.email,
                up.phone_number, up.company_name, up.job_title,
                up.website_url, up.linkedin_url, up.industry,
                up.city, up.state, up.zip_code, up.country,
                up.subject, up.message, up.budget_range,
                up.product_interest, up.referral_source,
                up.preferred_contact, up.best_time_to_contact,
                up.language, up.preferred_language,
                up.form_custom_field_1, up.form_custom_field_2, up.form_custom_field_3,
                up.dbc_username, up.dbc_password
            FROM users u
            LEFT JOIN user_profiles up ON u.id = up.user_id
            WHERE u.id = :user_id
        """)

        result = db.execute(query, {"user_id": str(user_id)}).mappings().first()

        if result:
            return {
                "first_name": result["first_name"] or "User",
                "last_name": result["last_name"] or "",
                "email": result["email"] or "contact@example.com",
                "phone_number": result["phone_number"] or "",
                "company_name": result["company_name"] or "",
                "job_title": result["job_title"] or "",
                "website_url": result["website_url"] or "",
                "linkedin_url": result["linkedin_url"] or "",
                "industry": result["industry"] or "",
                "city": result["city"] or "",
                "state": result["state"] or "",
                "zip_code": result["zip_code"] or "",
                "country": result["country"] or "",
                "subject": result["subject"] or "Business Inquiry",
                "message": result["message"] or "I would like to discuss business opportunities.",
                "budget_range": result["budget_range"] or "",
                "product_interest": result["product_interest"] or "",
                "referral_source": result["referral_source"] or "",
                "preferred_contact": result["preferred_contact"] or "",
                "best_time_to_contact": result["best_time_to_contact"] or "",
                "language": result["language"] or "",
                "preferred_language": result["preferred_language"] or "",
                "form_custom_field_1": result["form_custom_field_1"] or "",
                "form_custom_field_2": result["form_custom_field_2"] or "",
                "form_custom_field_3": result["form_custom_field_3"] or "",
                "dbc_username": result["dbc_username"] or "",
                "dbc_password": result["dbc_password"] or "",
            }
    except Exception as e:
        logger.warning(f"Could not fetch user profile: {e}")

    # Default profile if user not found or error
    return {
        "first_name": "User",
        "last_name": "",
        "email": "contact@example.com",
        "phone_number": "",
        "company_name": "",
        "job_title": "",
        "website_url": "",
        "linkedin_url": "",
        "industry": "",
        "city": "",
        "state": "",
        "zip_code": "",
        "country": "",
        "subject": "Business Inquiry",
        "message": "I would like to discuss business opportunities.",
        "budget_range": "",
        "product_interest": "",
        "referral_source": "",
        "preferred_contact": "",
        "best_time_to_contact": "",
        "language": "",
        "preferred_language": "",
        "form_custom_field_1": "",
        "form_custom_field_2": "",
        "form_custom_field_3": "",
        "dbc_username": "",
        "dbc_password": "",
    }


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request headers"""
    if not request:
        return "unknown"

    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    if request.client:
        return request.client.host

    return "unknown"


# ===========================
# MAIN CAMPAIGN CREATION WITH CSV AND AUTOMATION
# ===========================


@router.post("/start", response_model=None)
@log_function("start_campaign_with_csv")
async def start_campaign_with_csv(
    request: Request,
    name: str = Form(...),
    message: str = Form(...),
    file: UploadFile = File(...),
    proxy: Optional[str] = Form(None),
    use_captcha: bool = Form(False),
    settings: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Start campaign with CSV parsing, submission creation, and automation."""
    user_id_var.set(str(user.id))
    campaign_id = str(uuid.uuid4())
    campaign_id_var.set(campaign_id)

    logger.info(f"ðŸ“‹ Starting campaign creation: {campaign_id}")
    logger.info(f"ðŸ‘¤ User: {user.email} ({str(user.id)})")
    logger.info(f"ðŸ“ Campaign name: {name}")

    try:
        # Validate file
        if not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="File must be a CSV")

        # Parse CSV
        content = await file.read()
        valid_urls, processing_report = await CSVParserService.parse_csv_file(content)

        if processing_report.get("errors"):
            error_details = "; ".join(processing_report["errors"])
            raise HTTPException(
                status_code=400, detail=f"CSV parsing failed: {error_details}"
            )

        if not valid_urls:
            raise HTTPException(
                status_code=400, detail="No valid URLs found in CSV file"
            )

        total_urls = len(valid_urls)
        logger.info(f"âœ… Parsed {total_urls} valid URLs from CSV")

        # Create campaign in database
        now = datetime.utcnow()
        insert_query = text(
            """
            INSERT INTO campaigns (
                id, user_id, name, message, csv_filename, file_name,
                total_urls, total_websites, status, use_captcha, proxy,
                created_at, updated_at, started_at
            ) VALUES (
                :id, :user_id, :name, :message, :csv_filename, :file_name,
                :total_urls, :total_websites, :status, :use_captcha, :proxy,
                :created_at, :updated_at, :started_at
            )
        """
        )

        db.execute(
            insert_query,
            {
                "id": campaign_id,
                "user_id": str(user.id),
                "name": name.strip(),
                "message": message.strip() if message else None,
                "csv_filename": file.filename,
                "file_name": file.filename,
                "total_urls": total_urls,
                "total_websites": total_urls,
                "status": "PROCESSING",
                "use_captcha": use_captcha,
                "proxy": proxy if proxy else None,
                "created_at": now,
                "updated_at": now,
                "started_at": now,
            },
        )
        logger.info(f"âœ… Campaign record created in database")

        # Fetch user profile data for form filling
        user_profile = get_user_profile_for_campaign(db, user.id)
        logger.info(f"📋 User profile loaded: {user_profile.get('first_name', 'Unknown')} {user_profile.get('last_name', '')}")

        # Create submissions
        submission_service = SubmissionService(db)
        try:
            submissions, errors = submission_service.bulk_create_submissions(
                user_id=user.id, campaign_id=uuid.UUID(campaign_id), urls=valid_urls
            )

            if errors:
                logger.warning(f"âš ï¸ Some submissions had errors: {errors}")

            logger.info(f"âœ… Created {len(submissions)} submissions")

        except Exception as e:
            logger.error(f"âŒ Error creating submissions: {e}")
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to create submissions")

        # Commit database changes
        db.commit()
        logger.info(f"âœ… Database changes committed")

        # Start automation processing
        automation_started = False
        automation_error = None

        try:
            logger.info(f"ðŸ”„ Starting automation processor...")

            # Ensure Python can find our modules
            app_dir = os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            )
            if app_dir not in sys.path:
                sys.path.insert(0, app_dir)

            # Import the processor
            from app.workers.processors.subprocess_runner import (
                start_campaign_processing,
            )

            logger.info(f"âœ… Processor module imported successfully")

            # Start processing
            automation_started = start_campaign_processing(
                campaign_id=campaign_id, user_id=str(user.id)
            )

            if automation_started:
                logger.info(f"ðŸŽ‰ Automation processor started successfully!")
                logger.info(f"ðŸ“Š Campaign {campaign_id} is processing in background")
            else:
                logger.error(f"âš ï¸ Automation processor returned False")
                automation_error = "Processor failed to start"

        except ImportError as e:
            automation_error = f"Import error: {str(e)}"
            logger.error(f"âŒ Failed to import processor: {automation_error}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")

        except Exception as e:
            automation_error = str(e)
            logger.error(f"âŒ Failed to start automation: {automation_error}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")

        # Update campaign status if automation failed
        if not automation_started:
            logger.warning(f"âš ï¸ Updating campaign status to FAILED")
            update_query = text(
                """
                UPDATE campaigns 
                SET status = 'FAILED', 
                    error_message = :error_message,
                    updated_at = :updated_at
                WHERE id = :campaign_id
            """
            )
            db.execute(
                update_query,
                {
                    "campaign_id": campaign_id,
                    "error_message": f"Automation failed: {automation_error or 'Unknown error'}",
                    "updated_at": datetime.utcnow(),
                },
            )
            db.commit()

        # Return response
        return {
            "success": True,
            "message": "Campaign started successfully",
            "campaign_id": campaign_id,
            "total_urls": total_urls,
            "status": "PROCESSING" if automation_started else "FAILED",
            "automation_started": automation_started,
            "automation_error": automation_error,
            "user_profile": user_profile,
            "processing_report": {
                "valid_urls": processing_report.get("valid_urls", 0),
                "duplicates_removed": processing_report.get("duplicates_removed", 0),
                "invalid_urls": len(processing_report.get("invalid_urls", [])),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"âŒ Campaign creation error: {e}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start campaign: {str(e)}"
        )


# ===========================
# CAMPAIGN MANAGEMENT ENDPOINTS
# ===========================


@router.get("")
@log_function("list_campaigns")
def list_campaigns(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=100),
    status_filter: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List campaigns with filtering and pagination"""
    user_id_var.set(str(user.id))

    effective_limit = limit if limit is not None else per_page
    status_value = status_filter or status

    logger.info(f"Listing campaigns for user {user.email}")

    try:
        # Build base query
        base_query = """
            SELECT 
                id, user_id, name, status, csv_filename, file_name,
                total_urls, total_websites, processed, successful, failed,
                submitted_count, failed_count, email_fallback, no_form,
                message, proxy, use_captcha, error_message,
                created_at, updated_at, started_at, completed_at
            FROM campaigns 
            WHERE user_id = :user_id
        """

        params = {"user_id": str(user.id)}

        # Add status filter
        if status_value:
            status_upper = status_value.upper()
            if status_upper in ["ACTIVE", "RUNNING"]:
                base_query += (
                    " AND status IN ('ACTIVE', 'running', 'PROCESSING', 'RUNNING')"
                )
            elif status_upper in ["COMPLETED"]:
                base_query += " AND status IN ('COMPLETED', 'completed')"
            elif status_upper in ["FAILED"]:
                base_query += " AND status IN ('FAILED', 'failed')"
            else:
                base_query += " AND status = :status_value"
                params["status_value"] = status_value

        # Get total count
        count_query = f"SELECT COUNT(*) FROM ({base_query}) as count_query"
        total = db.execute(text(count_query), params).scalar() or 0

        # Add pagination
        paginated_query = (
            f"{base_query} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        offset = (page - 1) * effective_limit
        params.update({"limit": effective_limit, "offset": offset})

        # Execute query
        result = db.execute(text(paginated_query), params).mappings().all()

        # Format results
        campaigns = []
        for row in result:
            total_submissions = int(row.get("total_urls", 0) or 0)
            processed_submissions = int(row.get("processed", 0) or 0)
            successful_submissions = int(row.get("successful", 0) or 0)

            progress_percent = 0
            if total_submissions > 0:
                progress_percent = round(
                    (processed_submissions / total_submissions) * 100, 2
                )

            success_rate = 0
            if processed_submissions > 0:
                success_rate = round(
                    (successful_submissions / processed_submissions) * 100, 2
                )

            campaign_dict = {
                "id": str(row["id"]),
                "name": row.get("name", "Untitled Campaign"),
                "status": row.get("status", "draft"),
                "total_urls": total_submissions,
                "processed": processed_submissions,
                "successful": successful_submissions,
                "failed": int(row.get("failed", 0) or 0),
                "progress_percent": progress_percent,
                "success_rate": success_rate,
                "error_message": row.get("error_message"),
                "created_at": (
                    row["created_at"].isoformat() if row.get("created_at") else None
                ),
                "updated_at": (
                    row["updated_at"].isoformat() if row.get("updated_at") else None
                ),
            }
            campaigns.append(campaign_dict)

        logger.info(f"Found {len(campaigns)} campaigns")
        return campaigns

    except Exception as e:
        logger.error(f"Error listing campaigns: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch campaigns")


@router.get("/{campaign_id}")
@log_function("get_campaign")
def get_campaign(
    request: Request,
    campaign_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get a single campaign by ID"""
    user_id_var.set(str(user.id))
    campaign_id_var.set(str(campaign_id))

    try:
        query = text(
            """
            SELECT * FROM campaigns 
            WHERE id = :campaign_id AND user_id = :user_id
        """
        )

        result = (
            db.execute(
                query, {"campaign_id": str(campaign_id), "user_id": str(user.id)}
            )
            .mappings()
            .first()
        )

        if not result:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Format response
        row = result
        total_submissions = int(row.get("total_urls", 0) or 0)
        processed_submissions = int(row.get("processed", 0) or 0)
        successful_submissions = int(row.get("successful", 0) or 0)

        progress_percent = 0
        if total_submissions > 0:
            progress_percent = round(
                (processed_submissions / total_submissions) * 100, 2
            )

        success_rate = 0
        if processed_submissions > 0:
            success_rate = round(
                (successful_submissions / processed_submissions) * 100, 2
            )

        campaign = {
            "id": str(row["id"]),
            "name": row.get("name", "Untitled Campaign"),
            "status": row.get("status", "draft"),
            "total_urls": total_submissions,
            "processed": processed_submissions,
            "successful": successful_submissions,
            "failed": int(row.get("failed", 0) or 0),
            "progress_percent": progress_percent,
            "success_rate": success_rate,
            "error_message": row.get("error_message"),
            "created_at": (
                row["created_at"].isoformat() if row.get("created_at") else None
            ),
            "updated_at": (
                row["updated_at"].isoformat() if row.get("updated_at") else None
            ),
        }

        return campaign

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving campaign: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch campaign: {str(e)}"
        )


@router.get("/{campaign_id}/submissions")
@log_function("get_campaign_submissions")
def get_campaign_submissions(
    request: Request,
    campaign_id: UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get submissions for a campaign with error details"""
    user_id_var.set(str(user.id))
    campaign_id_var.set(str(campaign_id))
    
    try:
        # Verify campaign ownership
        campaign_check = db.execute(
            text("SELECT id FROM campaigns WHERE id = :id AND user_id = :uid"),
            {"id": str(campaign_id), "uid": str(user.id)}
        ).first()
        
        if not campaign_check:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        # Get submissions with pagination
        offset = (page - 1) * limit
        query = text("""
            SELECT 
                id, url, status, success, error_message, 
                created_at, updated_at, retry_count,
                captcha_encountered, captcha_solved
            FROM submissions 
            WHERE campaign_id = :campaign_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """)
        
        submissions = db.execute(
            query,
            {"campaign_id": str(campaign_id), "limit": limit, "offset": offset}
        ).mappings().all()
        
        # Get total count
        count_query = text("SELECT COUNT(*) FROM submissions WHERE campaign_id = :campaign_id")
        total = db.execute(count_query, {"campaign_id": str(campaign_id)}).scalar() or 0
        
        # Format results
        result = []
        for sub in submissions:
            result.append({
                "id": str(sub["id"]),
                "url": sub.get("url"),
                "status": sub.get("status"),
                "success": sub.get("success"),
                "error_message": sub.get("error_message"),
                "created_at": sub["created_at"].isoformat() if sub.get("created_at") else None,
                "updated_at": sub["updated_at"].isoformat() if sub.get("updated_at") else None,
                "retry_count": sub.get("retry_count") or 0,
                "captcha_encountered": sub.get("captcha_encountered"),
                "captcha_solved": sub.get("captcha_solved"),
            })
        
        return {
            "data": result,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": (total + limit - 1) // limit
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting campaign submissions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get submissions: {str(e)}")


@router.get("/{campaign_id}/status")
@log_function("get_campaign_status")
def get_campaign_status(
    request: Request,
    campaign_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get real-time campaign status"""
    user_id_var.set(str(user.id))
    campaign_id_var.set(str(campaign_id))

    try:
        status_query = text(
            """
            SELECT 
                status, 
                total_urls, 
                processed, 
                successful, 
                failed,
                error_message,
                CASE WHEN total_urls > 0 
                     THEN ROUND((processed * 100.0 / total_urls), 2) 
                     ELSE 0 END as progress_percent,
                CASE WHEN status IN ('COMPLETED', 'STOPPED', 'FAILED') 
                     THEN true ELSE false END as is_complete
            FROM campaigns 
            WHERE id = :campaign_id AND user_id = :user_id
        """
        )

        result = (
            db.execute(
                status_query, {"campaign_id": str(campaign_id), "user_id": str(user.id)}
            )
            .mappings()
            .first()
        )

        if not result:
            raise HTTPException(status_code=404, detail="Campaign not found")

        return {
            "campaign_id": str(campaign_id),
            "status": result["status"],
            "total": result["total_urls"] or 0,
            "processed": result["processed"] or 0,
            "successful": result["successful"] or 0,
            "failed": result["failed"] or 0,
            "progress_percent": float(result["progress_percent"] or 0),
            "is_complete": result["is_complete"],
            "error_message": result.get("error_message"),
            "message": (
                "Campaign processing completed"
                if result["is_complete"]
                else "Campaign in progress"
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting campaign status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get campaign status: {str(e)}"
        )


@router.get("/{campaign_id}/analytics")
@log_function("get_campaign_analytics")
def get_campaign_analytics(
    request: Request,
    campaign_id: UUID,
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get aggregated analytics for a campaign."""
    user_id_var.set(str(user.id))
    campaign_id_var.set(str(campaign_id))

    try:
        # Verify campaign belongs to user
        campaign_check = text(
            """
            SELECT id FROM campaigns
            WHERE id = :campaign_id AND user_id = :user_id
        """
        )
        exists = db.execute(
            campaign_check,
            {"campaign_id": str(campaign_id), "user_id": str(user.id)},
        ).first()

        if not exists:
            raise HTTPException(status_code=404, detail="Campaign not found")

        window_start = datetime.utcnow() - timedelta(days=days)

        stats_query = text(
            """
            SELECT
                COUNT(*)::int AS total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::int AS successful,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)::int AS failed,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END)::int AS processing,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END)::int AS pending,
                SUM(CASE WHEN status = 'retry' THEN 1 ELSE 0 END)::int AS retry
            FROM submissions
            WHERE campaign_id = :campaign_id
              AND created_at >= :window_start
        """
        )

        stats_row = (
            db.execute(
                stats_query,
                {"campaign_id": str(campaign_id), "window_start": window_start},
            )
            .mappings()
            .first()
        ) or {}

        total = stats_row.get("total", 0) or 0
        successful = stats_row.get("successful", 0) or 0
        failed = stats_row.get("failed", 0) or 0
        processed = successful + failed
        pending = stats_row.get("pending", 0) or 0
        retry = stats_row.get("retry", 0) or 0

        daily_query = text(
            """
            SELECT
                DATE_TRUNC('day', COALESCE(processed_at, updated_at, created_at))::date AS day,
                COUNT(*)::int AS total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)::int AS successful,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)::int AS failed
            FROM submissions
            WHERE campaign_id = :campaign_id
              AND created_at >= :window_start
            GROUP BY day
            ORDER BY day
        """
        )

        daily_rows = db.execute(
            daily_query,
            {"campaign_id": str(campaign_id), "window_start": window_start},
        ).mappings()

        daily_stats = [
            {
                "day": row["day"].isoformat(),
                "total": row["total"],
                "successful": row["successful"],
                "failed": row["failed"],
            }
            for row in daily_rows
        ]

        success_rate = round((successful / max(processed, 1)) * 100, 2) if processed else 0.0

        return {
            "campaign_id": str(campaign_id),
            "time_window_days": days,
            "total_submissions": total,
            "processed": processed,
            "successful": successful,
            "failed": failed,
            "pending": pending,
            "retry": retry,
            "success_rate": success_rate,
            "daily_stats": daily_stats,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get campaign analytics",
            extra={
                "event": "campaign_analytics_failed",
                "campaign_id": str(campaign_id),
                "user_id": str(user.id),
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to get campaign analytics")

@router.post("/{campaign_id}/actions", response_model=CampaignActionResponse)
@log_function("campaign_action")
async def campaign_action(
    request: Request,
    campaign_id: UUID,
    action_request: CampaignActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Perform campaign control actions (pause/resume/stop/cancel)."""
    user_id_var.set(str(user.id))
    campaign_id_var.set(str(campaign_id))

    try:
        logger.info(
            "Campaign action requested",
            extra={
                "event": "campaign_action_requested",
                "campaign_id": str(campaign_id),
                "user_id": str(user.id),
                "action": action_request.action,
                "reason": action_request.reason,
            },
        )

        query = text(
            """
            SELECT id, status FROM campaigns
            WHERE id = :campaign_id AND user_id = :user_id
        """
        )
        campaign = (
            db.execute(
                query, {"campaign_id": str(campaign_id), "user_id": str(user.id)}
            )
            .mappings()
            .first()
        )

        if not campaign:
            raise HTTPException(status_code=404, detail="Campaign not found")

        old_status = campaign.get("status") or CampaignStatus.DRAFT.value
        requested_action = action_request.action.lower()
        warnings: List[str] = []
        timestamp = datetime.utcnow()

        def update_campaign_status(new_status: CampaignStatus, error_message: str = None):
            db.execute(
                text(
                    """
                    UPDATE campaigns
                    SET status = :status,
                        updated_at = :updated_at,
                        error_message = :error_message
                    WHERE id = :campaign_id
                """
                ),
                {
                    "status": new_status.value,
                    "updated_at": timestamp,
                    "error_message": error_message,
                    "campaign_id": str(campaign_id),
                },
            )

        def reset_processing_submissions(set_failed: bool = False, failure_reason: str = None):
            if set_failed:
                db.execute(
                    text(
                        """
                        UPDATE submissions
                        SET status = 'failed',
                            error_message = :reason,
                            updated_at = :updated_at
                        WHERE campaign_id = :campaign_id
                          AND status IN ('pending', 'processing')
                    """
                    ),
                    {
                        "reason": failure_reason or "Campaign stopped by user",
                        "updated_at": timestamp,
                        "campaign_id": str(campaign_id),
                    },
                )
            else:
                db.execute(
                    text(
                        """
                        UPDATE submissions
                        SET status = 'pending',
                            updated_at = :updated_at
                        WHERE campaign_id = :campaign_id
                          AND status = 'processing'
                    """
                    ),
                    {"updated_at": timestamp, "campaign_id": str(campaign_id)},
                )

        def commit_changes():
            try:
                db.commit()
            except Exception as commit_error:
                db.rollback()
                raise commit_error

        if requested_action == "pause":
            if old_status not in [
                CampaignStatus.RUNNING.value,
                CampaignStatus.PROCESSING.value,
                CampaignStatus.QUEUED.value,
            ] and not action_request.force:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot pause campaign in status {old_status}",
                )

            update_campaign_status(CampaignStatus.PAUSED)
            reset_processing_submissions(set_failed=False)
            commit_changes()

            stop_result = stop_processor(str(campaign_id))
            if not stop_result.get("success", False):
                warnings.append(stop_result.get("message", "Failed to pause worker"))

            message = "Campaign paused successfully"
            new_status = CampaignStatus.PAUSED.value

        elif requested_action == "resume":
            if old_status not in [
                CampaignStatus.PAUSED.value,
                CampaignStatus.STOPPED.value,
            ]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot resume campaign in status {old_status}",
                )

            update_campaign_status(CampaignStatus.QUEUED)
            commit_changes()

            if not start_campaign_processing(str(campaign_id), str(user.id)):
                warnings.append("Campaign processor failed to start")
                update_campaign_status(
                    CampaignStatus.FAILED, "Failed to resume campaign"
                )
                commit_changes()
                raise HTTPException(
                    status_code=500, detail="Failed to resume campaign processing"
                )

            message = "Campaign resumed successfully"
            new_status = CampaignStatus.QUEUED.value

        elif requested_action in {"stop", "cancel"}:
            if old_status in [
                CampaignStatus.COMPLETED.value,
                CampaignStatus.FAILED.value,
                CampaignStatus.CANCELLED.value,
                CampaignStatus.STOPPED.value,
            ] and not action_request.force:
                raise HTTPException(
                    status_code=400,
                    detail=f"Campaign already {old_status.lower()}",
                )

            target_status = (
                CampaignStatus.CANCELLED
                if requested_action == "cancel"
                else CampaignStatus.STOPPED
            )

            update_campaign_status(target_status, action_request.reason)
            reset_processing_submissions(
                set_failed=True,
                failure_reason=action_request.reason or "Campaign stopped by user",
            )
            commit_changes()

            stop_result = stop_processor(str(campaign_id))
            if not stop_result.get("success", False):
                warnings.append(stop_result.get("message", "Failed to stop worker"))

            message = (
                "Campaign cancelled successfully"
                if requested_action == "cancel"
                else "Campaign stopped successfully"
            )
            new_status = target_status.value

        else:
            raise HTTPException(status_code=400, detail="Unsupported campaign action")

        logger.info(
            "Campaign action completed",
            extra={
                "event": "campaign_action_completed",
                "campaign_id": str(campaign_id),
                "user_id": str(user.id),
                "action": requested_action,
                "old_status": old_status,
                "new_status": new_status,
                "warnings": warnings,
            },
        )

        return CampaignActionResponse(
            success=True,
            message=message,
            campaign_id=str(campaign_id),
            old_status=old_status,
            new_status=new_status,
            warnings=warnings or None,
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            "Campaign action failed",
            extra={
                "event": "campaign_action_failed",
                "campaign_id": str(campaign_id),
                "user_id": str(user.id),
                "action": action_request.action,
                "error": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to perform campaign action")


@router.post("/{campaign_id}/pause", response_model=CampaignActionResponse)
async def pause_campaign(
    request: Request,
    campaign_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Alias endpoint for pausing a campaign."""
    action_request = CampaignActionRequest(action="pause")
    return await campaign_action(request, campaign_id, action_request, db, user)


@router.post("/{campaign_id}/resume", response_model=CampaignActionResponse)
async def resume_campaign(
    request: Request,
    campaign_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Alias endpoint for resuming a campaign."""
    action_request = CampaignActionRequest(action="resume")
    return await campaign_action(request, campaign_id, action_request, db, user)


@router.post("/{campaign_id}/stop", response_model=CampaignActionResponse)
async def stop_campaign(
    request: Request,
    campaign_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Alias endpoint for stopping a campaign."""
    action_request = CampaignActionRequest(action="stop")
    return await campaign_action(request, campaign_id, action_request, db, user)

@router.delete("/{campaign_id}")
@log_function("delete_campaign")
def delete_campaign(
    request: Request,
    campaign_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a campaign"""
    user_id_var.set(str(user.id))
    campaign_id_var.set(str(campaign_id))

    try:
        # Check if campaign exists
        check_query = text(
            """
            SELECT name, status FROM campaigns 
            WHERE id = :campaign_id AND user_id = :user_id
        """
        )

        result = (
            db.execute(
                check_query, {"campaign_id": str(campaign_id), "user_id": str(user.id)}
            )
            .mappings()
            .first()
        )

        if not result:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # Check if campaign can be deleted
        if result["status"] in ["ACTIVE", "running", "PROCESSING"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete a running campaign. Please stop it first.",
            )

        # Delete related submissions
        delete_submissions = text(
            "DELETE FROM submissions WHERE campaign_id = :campaign_id"
        )
        submissions_deleted = db.execute(
            delete_submissions, {"campaign_id": str(campaign_id)}
        ).rowcount

        # Delete the campaign
        delete_campaign_query = text("DELETE FROM campaigns WHERE id = :campaign_id")
        db.execute(delete_campaign_query, {"campaign_id": str(campaign_id)})

        db.commit()

        logger.info(
            f"Campaign {campaign_id} deleted with {submissions_deleted} submissions"
        )

        return {
            "success": True,
            "message": f"Campaign and {submissions_deleted} submissions deleted successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting campaign: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete campaign: {str(e)}"
        )


# ===========================
# TEST ENDPOINTS
# ===========================


@router.get("/test-import")
def test_import():
    """Test if processor can be imported"""
    try:
        from app.workers.processors.subprocess_runner import start_campaign_processing

        return {"success": True, "message": "Import successful"}
    except ImportError as e:
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@router.get("/test-processor/{campaign_id}")
def test_processor(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test the processor directly"""
    try:
        from app.workers.processors.subprocess_runner import start_campaign_processing

        result = start_campaign_processing(
            campaign_id=campaign_id, user_id=str(current_user.id)
        )

        return {
            "processor_started": result,
            "campaign_id": campaign_id,
            "message": "Check backend console for processor logs",
        }
    except Exception as e:
        return {
            "processor_started": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }
