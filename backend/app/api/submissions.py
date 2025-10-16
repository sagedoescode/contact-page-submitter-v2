"""Enhanced Submissions API endpoints with optimized logging."""

from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import time
import uuid
import json
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.log_service import LogService as ApplicationInsightsLogger
from app.logging import get_logger, log_function
from app.logging.core import request_id_var, user_id_var, campaign_id_var

# Initialize structured logger
logger = get_logger(__name__)

# Create FastAPI router
router = APIRouter(tags=["submissions"], redirect_slashes=False)

# Simulated submission storage (replace with actual database)
SUBMISSIONS_DB = {}
SUBMISSION_STATS = {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "spam": 0}

# Spam detection keywords
SPAM_KEYWORDS = ["viagra", "casino", "lottery", "prize", "winner", "bitcoin", "crypto"]


# Pydantic models for request/response
class SubmissionCreateRequest(BaseModel):
    title: str = Field(..., max_length=200)
    content: str = Field(..., max_length=10000)
    type: str = Field(...)
    metadata: Optional[Dict[str, Any]] = Field(default={})


class StatusUpdateRequest(BaseModel):
    status: str
    reason: Optional[str] = ""


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


def validate_submission_data(data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Validate submission data."""
    required_fields = ["title", "content", "type"]

    for field in required_fields:
        if field not in data or not data[field]:
            return False, f"Missing required field: {field}"

    # Validate content length
    if len(data.get("content", "")) > 10000:
        return False, "Content too long (max 10000 characters)"

    if len(data.get("title", "")) > 200:
        return False, "Title too long (max 200 characters)"

    # Validate submission type
    valid_types = ["form", "feedback", "report", "inquiry", "application"]
    if data.get("type") not in valid_types:
        return (
            False,
            f"Invalid submission type. Must be one of: {', '.join(valid_types)}",
        )

    return True, None


def check_spam(submission_data: Dict[str, Any]) -> bool:
    """Check if submission is spam."""
    content = submission_data.get("content", "").lower()
    title = submission_data.get("title", "").lower()

    for keyword in SPAM_KEYWORDS:
        if keyword in content or keyword in title:
            return True

    # Check for excessive links
    link_count = content.count("http://") + content.count("https://")
    if link_count > 5:
        return True

    return False


def is_admin(user: User) -> bool:
    """Check if user is an admin."""
    # Implement your actual admin check logic
    # return user.role == "admin"
    return False


@router.post("/submit")
@log_function("create_submission")
async def create_submission(
    request: Request,
    submission_data: SubmissionCreateRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(lambda: None),  # Allow anonymous
):
    """Create a new submission."""
    try:
        data = submission_data.model_dump()
        client_ip = get_client_ip(request)

        # Get user context
        user_id = str(current_user.id) if current_user else "anonymous"
        if current_user:
            user_id_var.set(user_id)

        # Validate submission data
        is_valid, error_message = validate_submission_data(data)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_message)

        # Check for spam
        is_spam = check_spam(data)

        # Create submission
        submission_id = str(uuid.uuid4())
        submission = {
            "id": submission_id,
            "user_id": user_id,
            "title": data["title"],
            "content": data["content"],
            "type": data["type"],
            "metadata": data.get("metadata", {}),
            "status": "spam" if is_spam else "pending",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "ip_address": client_ip,
            "user_agent": request.headers.get("User-Agent", "Unknown"),
        }

        # Store submission
        SUBMISSIONS_DB[submission_id] = submission

        # Update stats
        SUBMISSION_STATS["total"] += 1

        if is_spam:
            SUBMISSION_STATS["spam"] += 1

            # Log spam detection
            logger.security_event(
                event="spam_submission_detected",
                severity="warning",
                properties={
                    "submission_id": submission_id,
                    "submission_type": data["type"],
                    "user_id": user_id,
                    "ip": client_ip,
                },
            )

            # Track in ApplicationInsights
            app_logger = ApplicationInsightsLogger(db)
            app_logger.track_security_event(
                event_name="spam_submission",
                user_id=user_id,
                ip_address=client_ip,
                success=False,
                details={
                    "submission_id": submission_id,
                    "submission_type": data["type"],
                },
            )
        else:
            SUBMISSION_STATS["pending"] += 1

            # Only log non-spam submissions of important types
            if data["type"] in ["report", "application"]:
                logger.info(
                    "Important submission created",
                    extra={
                        "submission_id": submission_id,
                        "type": data["type"],
                        "user_id": user_id,
                    },
                )

        return {
            "success": True,
            "submission_id": submission_id,
            "status": submission["status"],
            "message": "Submission created successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to create submission",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "ip": get_client_ip(request),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to create submission")


@router.get("/{submission_id}")
@log_function("get_submission")
async def get_submission(
    submission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific submission."""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    try:
        # Check if submission exists
        if submission_id not in SUBMISSIONS_DB:
            raise HTTPException(status_code=404, detail="Submission not found")

        submission = SUBMISSIONS_DB[submission_id]

        # Check access permissions
        if submission["user_id"] != user_id and not is_admin(current_user):
            # Log unauthorized access attempt
            logger.security_event(
                event="unauthorized_submission_access",
                severity="warning",
                properties={
                    "submission_id": submission_id,
                    "user_id": user_id,
                    "owner_id": submission["user_id"],
                    "ip": get_client_ip(request),
                },
            )

            raise HTTPException(status_code=403, detail="Unauthorized access")

        # No logging for successful retrieval
        return {"success": True, "submission": submission}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to retrieve submission",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "submission_id": submission_id,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve submission")


@router.get("/list")
async def list_submissions(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
):
    """List submissions with filtering and pagination."""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    try:
        # Filter submissions
        filtered_submissions = []
        for submission_id, submission in SUBMISSIONS_DB.items():
            # Check access
            if submission["user_id"] != user_id and not is_admin(current_user):
                continue

            # Apply filters
            if status and submission["status"] != status:
                continue
            if type and submission["type"] != type:
                continue

            filtered_submissions.append(submission)

        # Sort submissions
        reverse_order = sort_order == "desc"
        if sort_by == "created_at":
            filtered_submissions.sort(
                key=lambda x: x["created_at"], reverse=reverse_order
            )
        elif sort_by == "status":
            filtered_submissions.sort(key=lambda x: x["status"], reverse=reverse_order)

        # Paginate
        total = len(filtered_submissions)
        start = (page - 1) * per_page
        end = start + per_page
        paginated = filtered_submissions[start:end]

        # No logging for routine list operations

        return {
            "success": True,
            "submissions": paginated,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": (total + per_page - 1) // per_page,
            },
        }

    except Exception as e:
        logger.error(
            "Failed to list submissions",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to list submissions")


@router.put("/{submission_id}/status")
@log_function("update_submission_status")
async def update_submission_status(
    submission_id: str,
    status_data: StatusUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update submission status (admin only)."""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    try:
        new_status = status_data.status
        reason = status_data.reason

        # Validate status
        valid_statuses = ["pending", "reviewing", "approved", "rejected", "spam"]
        if new_status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f'Invalid status. Must be one of: {", ".join(valid_statuses)}',
            )

        # Check if submission exists
        if submission_id not in SUBMISSIONS_DB:
            raise HTTPException(status_code=404, detail="Submission not found")

        submission = SUBMISSIONS_DB[submission_id]
        old_status = submission["status"]

        # Check admin permission
        if not is_admin(current_user):
            # Check if user owns submission and can only cancel
            if submission["user_id"] != user_id or new_status != "cancelled":
                raise HTTPException(status_code=403, detail="Admin access required")

        # Update status
        submission["status"] = new_status
        submission["status_reason"] = reason
        submission["status_updated_by"] = user_id
        submission["status_updated_at"] = datetime.utcnow().isoformat()
        submission["updated_at"] = datetime.utcnow().isoformat()

        # Update stats
        if old_status in SUBMISSION_STATS:
            SUBMISSION_STATS[old_status] = max(0, SUBMISSION_STATS[old_status] - 1)
        if new_status in SUBMISSION_STATS:
            SUBMISSION_STATS[new_status] += 1

        # Log important status changes only
        if new_status in ["approved", "rejected"]:
            logger.info(
                f"Submission {new_status}",
                extra={
                    "submission_id": submission_id,
                    "user_id": user_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "reason": reason,
                    "ip": get_client_ip(request),
                },
            )

            # Track in ApplicationInsights
            app_logger = ApplicationInsightsLogger(db)
            app_logger.track_security_event(
                event_name=f"submission_{new_status}",
                user_id=user_id,
                ip_address=get_client_ip(request),
                success=True,
                details={
                    "submission_id": submission_id,
                    "reason": reason,
                    "old_status": old_status,
                },
            )

        return {
            "success": True,
            "message": "Status updated successfully",
            "old_status": old_status,
            "new_status": new_status,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update submission status",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "submission_id": submission_id,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update status")


@router.delete("/{submission_id}")
async def delete_submission(
    submission_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a submission."""
    user_id = str(current_user.id)
    user_id_var.set(user_id)

    try:
        # Check if submission exists
        if submission_id not in SUBMISSIONS_DB:
            raise HTTPException(status_code=404, detail="Submission not found")

        submission = SUBMISSIONS_DB[submission_id]

        # Check permissions
        if submission["user_id"] != user_id and not is_admin(current_user):
            # Log unauthorized delete attempt
            logger.security_event(
                event="unauthorized_submission_delete",
                severity="warning",
                properties={
                    "submission_id": submission_id,
                    "user_id": user_id,
                    "owner_id": submission["user_id"],
                    "ip": get_client_ip(request),
                },
            )

            raise HTTPException(status_code=403, detail="Unauthorized")

        # Delete submission
        status_val = submission["status"]
        submission_type = submission["type"]
        del SUBMISSIONS_DB[submission_id]

        # Update stats
        if status_val in SUBMISSION_STATS:
            SUBMISSION_STATS[status_val] = max(0, SUBMISSION_STATS[status_val] - 1)
        SUBMISSION_STATS["total"] = max(0, SUBMISSION_STATS["total"] - 1)

        # Only log deletion of important submissions
        if submission_type in ["report", "application"]:
            logger.info(
                "Important submission deleted",
                extra={
                    "submission_id": submission_id,
                    "submission_type": submission_type,
                    "user_id": user_id,
                    "ip": get_client_ip(request),
                },
            )

        return {"success": True, "message": "Submission deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete submission",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "submission_id": submission_id,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to delete submission")


@router.get("/stats")
async def get_submission_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get submission statistics."""
    user_id_var.set(str(current_user.id))

    try:
        # Calculate additional stats
        stats = SUBMISSION_STATS.copy()

        # Add time-based stats
        now = datetime.utcnow()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        this_week = now - timedelta(days=now.weekday())
        this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        stats["today"] = 0
        stats["this_week"] = 0
        stats["this_month"] = 0

        for submission in SUBMISSIONS_DB.values():
            created_at = datetime.fromisoformat(submission["created_at"])
            if created_at >= today:
                stats["today"] += 1
            if created_at >= this_week:
                stats["this_week"] += 1
            if created_at >= this_month:
                stats["this_month"] += 1

        # Calculate rates
        if stats["total"] > 0:
            stats["approval_rate"] = round(
                (stats.get("approved", 0) / stats["total"]) * 100, 2
            )
            stats["spam_rate"] = round((stats.get("spam", 0) / stats["total"]) * 100, 2)
        else:
            stats["approval_rate"] = 0
            stats["spam_rate"] = 0

        # Only log if high spam rate detected
        if stats["spam_rate"] > 30:
            logger.warning(
                "High spam rate detected",
                extra={
                    "spam_rate": stats["spam_rate"],
                    "total_spam": stats.get("spam", 0),
                    "total_submissions": stats["total"],
                },
            )

        return {
            "success": True,
            "stats": stats,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(
            "Failed to get submission statistics",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve statistics")
