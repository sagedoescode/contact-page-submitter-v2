# app/api/campaigns.py - Complete Working Version
import time
import uuid
import csv
import io
import os
import sys
import traceback
from datetime import datetime
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

# Initialize structured logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"], redirect_slashes=False)


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
