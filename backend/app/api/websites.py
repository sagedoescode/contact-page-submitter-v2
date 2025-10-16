# app/api/websites.py - Website management API with optimized logging
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List, Literal, Union
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.log_service import LogService as ApplicationInsightsLogger
from app.logging import get_logger, log_function
from app.logging.core import request_id_var, user_id_var, campaign_id_var

# Initialize structured logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api/websites", tags=["websites"], redirect_slashes=False)


class WebsiteResponse(BaseModel):
    id: str
    campaign_id: Optional[str]
    domain: Optional[str]
    contact_url: Optional[str]
    form_detected: Optional[bool]
    form_type: Optional[str]
    form_labels: Optional[List[str]]
    form_field_count: Optional[int]
    has_captcha: Optional[bool]
    captcha_type: Optional[str]
    form_name_variants: Optional[List[str]]
    status: Optional[str]
    failure_reason: Optional[str]
    requires_proxy: Optional[bool]
    proxy_block_type: Optional[str]
    last_proxy_used: Optional[str]
    captcha_difficulty: Optional[str]
    captcha_solution_time: Optional[int]
    captcha_metadata: Optional[Dict[str, Any]]
    form_field_types: Optional[Dict[str, Any]]
    form_field_options: Optional[Dict[str, Any]]
    question_answer_fields: Optional[Dict[str, Any]]
    created_at: Optional[str]
    updated_at: Optional[str]
    user_id: Optional[str]


class WebsiteCreateRequest(BaseModel):
    campaign_id: str
    domain: str = Field(..., min_length=1, max_length=255)
    contact_url: str = Field(..., min_length=1)


class WebsiteUpdateRequest(BaseModel):
    domain: Optional[str] = Field(None, min_length=1, max_length=255)
    contact_url: Optional[str] = Field(None, min_length=1)
    form_detected: Optional[bool] = None
    form_type: Optional[str] = Field(None, max_length=100)
    has_captcha: Optional[bool] = None
    captcha_type: Optional[str] = Field(None, max_length=100)
    status: Optional[str] = Field(
        None, pattern="^(pending|processing|completed|failed)$"
    )
    failure_reason: Optional[str] = None


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

    return request.client.host if request.client else "unknown"


@router.post("/", response_model=WebsiteResponse)
@log_function("create_website")
async def create_website(
    request: Request,
    website_data: WebsiteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new website"""
    user_id_var.set(str(current_user.id))
    campaign_id_var.set(website_data.campaign_id)

    website_id = str(uuid.uuid4())

    try:
        # Verify campaign belongs to user
        campaign_check = text(
            """
            SELECT id FROM campaigns 
            WHERE id = :campaign_id AND user_id = :user_id
        """
        )

        campaign_exists = (
            db.execute(
                campaign_check,
                {
                    "campaign_id": website_data.campaign_id,
                    "user_id": str(current_user.id),
                },
            )
            .mappings()
            .first()
        )

        if not campaign_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
            )

        # Create website record
        insert_query = text(
            """
            INSERT INTO websites (
                id, campaign_id, user_id, domain, contact_url, status, 
                form_detected, has_captcha, created_at, updated_at
            ) VALUES (
                :id, :campaign_id, :user_id, :domain, :contact_url, 'pending',
                false, false, :created_at, :updated_at
            )
        """
        )

        params = {
            "id": website_id,
            "campaign_id": website_data.campaign_id,
            "user_id": str(current_user.id),
            "domain": website_data.domain.strip(),
            "contact_url": website_data.contact_url.strip(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        db.execute(insert_query, params)
        db.commit()

        # Fetch the created website
        select_query = text(
            """
            SELECT * FROM websites WHERE id = :website_id
        """
        )

        website_result = (
            db.execute(select_query, {"website_id": website_id}).mappings().first()
        )

        # Convert to response model
        website_dict = dict(website_result)
        for key, value in website_dict.items():
            if hasattr(value, "isoformat"):
                website_dict[key] = value.isoformat()

        # Only log website creation for audit
        logger.info(
            "Website created",
            extra={
                "website_id": website_id,
                "campaign_id": website_data.campaign_id,
                "domain": website_data.domain,
            },
        )

        return WebsiteResponse(**website_dict)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            "Database error during website creation",
            extra={
                "campaign_id": website_data.campaign_id,
                "website_id": website_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create website",
        )


@router.get("/", response_model=List[WebsiteResponse])
async def get_websites(
    request: Request,
    campaign_id: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get websites for the current user"""
    user_id_var.set(str(current_user.id))
    if campaign_id:
        campaign_id_var.set(campaign_id)

    try:
        # Build query with filters
        where_parts = ["user_id = :user_id"]
        params = {"user_id": str(current_user.id)}

        if campaign_id:
            where_parts.append("campaign_id = :campaign_id")
            params["campaign_id"] = campaign_id

        if status_filter:
            where_parts.append("status = :status")
            params["status"] = status_filter

        where_clause = " AND ".join(where_parts)

        # Count query
        count_query = text(
            f"""
            SELECT COUNT(*) FROM websites WHERE {where_clause}
        """
        )

        total = db.execute(count_query, params).scalar() or 0

        # Data query
        data_query = text(
            f"""
            SELECT * FROM websites 
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """
        )

        params.update({"limit": page_size, "offset": (page - 1) * page_size})

        websites_result = db.execute(data_query, params).mappings().all()

        # Convert results
        websites = []
        for website in websites_result:
            website_dict = dict(website)
            for key, value in website_dict.items():
                if hasattr(value, "isoformat"):
                    website_dict[key] = value.isoformat()
            websites.append(WebsiteResponse(**website_dict))

        # No logging for routine list operations

        return websites

    except SQLAlchemyError as e:
        logger.error(
            "Database error retrieving websites",
            extra={
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve websites",
        )


@router.get("/{website_id}", response_model=WebsiteResponse)
async def get_website(
    website_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific website by ID"""
    user_id_var.set(str(current_user.id))

    try:
        select_query = text(
            """
            SELECT * FROM websites 
            WHERE id = :website_id AND user_id = :user_id
        """
        )

        website_result = (
            db.execute(
                select_query,
                {"website_id": website_id, "user_id": str(current_user.id)},
            )
            .mappings()
            .first()
        )

        if not website_result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
            )

        # Convert to response model
        website_dict = dict(website_result)
        for key, value in website_dict.items():
            if hasattr(value, "isoformat"):
                website_dict[key] = value.isoformat()

        # Set campaign context if available
        if website_dict.get("campaign_id"):
            campaign_id_var.set(website_dict["campaign_id"])

        # No logging for routine retrieval

        return WebsiteResponse(**website_dict)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.error(
            "Database error retrieving website",
            extra={
                "website_id": website_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve website",
        )


@router.put("/{website_id}", response_model=WebsiteResponse)
@log_function("update_website")
async def update_website(
    website_id: str,
    website_data: WebsiteUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a website"""
    user_id_var.set(str(current_user.id))

    try:
        # Track what fields are being updated
        updated_data = website_data.model_dump(exclude_unset=True)
        updated_fields = [k for k, v in updated_data.items() if v is not None]

        # First, verify website exists and belongs to user
        check_query = text(
            """
            SELECT campaign_id, status, domain FROM websites 
            WHERE id = :website_id AND user_id = :user_id
        """
        )

        existing_website = (
            db.execute(
                check_query, {"website_id": website_id, "user_id": str(current_user.id)}
            )
            .mappings()
            .first()
        )

        if not existing_website:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
            )

        # Set campaign context
        if existing_website["campaign_id"]:
            campaign_id_var.set(existing_website["campaign_id"])

        # Build update query
        update_parts = []
        params = {"website_id": website_id, "user_id": str(current_user.id)}

        for field, value in updated_data.items():
            if value is not None:
                update_parts.append(f"{field} = :{field}")
                if isinstance(value, str):
                    params[field] = value.strip()
                else:
                    params[field] = value

        if update_parts:
            update_parts.append("updated_at = :updated_at")
            params["updated_at"] = datetime.utcnow()

            update_query = text(
                f"""
                UPDATE websites 
                SET {', '.join(update_parts)}
                WHERE id = :website_id AND user_id = :user_id
            """
            )

            db.execute(update_query, params)
            db.commit()

        # Fetch updated website
        select_query = text(
            """
            SELECT * FROM websites 
            WHERE id = :website_id AND user_id = :user_id
        """
        )

        updated_website = (
            db.execute(
                select_query,
                {"website_id": website_id, "user_id": str(current_user.id)},
            )
            .mappings()
            .first()
        )

        # Convert to response model
        website_dict = dict(updated_website)
        for key, value in website_dict.items():
            if hasattr(value, "isoformat"):
                website_dict[key] = value.isoformat()

        # Only log significant status changes
        if "status" in updated_fields and website_dict["status"] in [
            "completed",
            "failed",
        ]:
            logger.info(
                f"Website {website_dict['status']}",
                extra={
                    "website_id": website_id,
                    "domain": existing_website["domain"],
                    "previous_status": existing_website["status"],
                    "new_status": website_dict["status"],
                },
            )

        return WebsiteResponse(**website_dict)

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            "Database error updating website",
            extra={
                "website_id": website_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update website",
        )


@router.delete("/{website_id}")
@log_function("delete_website")
async def delete_website(
    website_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a website"""
    user_id_var.set(str(current_user.id))

    try:
        # First, verify website exists and get details for logging
        check_query = text(
            """
            SELECT domain, status, campaign_id FROM websites 
            WHERE id = :website_id AND user_id = :user_id
        """
        )

        existing_website = (
            db.execute(
                check_query, {"website_id": website_id, "user_id": str(current_user.id)}
            )
            .mappings()
            .first()
        )

        if not existing_website:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Website not found"
            )

        # Set campaign context
        if existing_website["campaign_id"]:
            campaign_id_var.set(existing_website["campaign_id"])

        # Delete related submissions first
        delete_submissions_query = text(
            """
            DELETE FROM submissions WHERE website_id = :website_id
        """
        )
        submissions_deleted = db.execute(
            delete_submissions_query, {"website_id": website_id}
        ).rowcount

        # Delete the website
        delete_query = text(
            """
            DELETE FROM websites 
            WHERE id = :website_id AND user_id = :user_id
        """
        )

        result = db.execute(
            delete_query, {"website_id": website_id, "user_id": str(current_user.id)}
        )

        db.commit()

        # Log deletion for audit trail
        logger.info(
            "Website deleted",
            extra={
                "website_id": website_id,
                "domain": existing_website["domain"],
                "campaign_id": existing_website["campaign_id"],
                "submissions_deleted": submissions_deleted,
                "ip": get_client_ip(request),
            },
        )

        return {"message": "Website deleted successfully"}

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            "Database error deleting website",
            extra={
                "website_id": website_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete website",
        )


@router.get("/campaign/{campaign_id}/stats")
async def get_campaign_website_stats(
    campaign_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get website statistics for a campaign"""
    user_id_var.set(str(current_user.id))
    campaign_id_var.set(campaign_id)

    try:
        # Verify campaign belongs to user
        campaign_check = text(
            """
            SELECT id FROM campaigns 
            WHERE id = :campaign_id AND user_id = :user_id
        """
        )

        campaign_exists = (
            db.execute(
                campaign_check,
                {"campaign_id": campaign_id, "user_id": str(current_user.id)},
            )
            .mappings()
            .first()
        )

        if not campaign_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
            )

        # Get website statistics
        stats_query = text(
            """
            SELECT 
                status,
                COUNT(*) as count,
                COUNT(CASE WHEN form_detected = true THEN 1 END) as with_forms,
                COUNT(CASE WHEN has_captcha = true THEN 1 END) as with_captcha,
                COUNT(CASE WHEN requires_proxy = true THEN 1 END) as requires_proxy
            FROM websites 
            WHERE campaign_id = :campaign_id
            GROUP BY status
            
            UNION ALL
            
            SELECT 
                'total' as status,
                COUNT(*) as count,
                COUNT(CASE WHEN form_detected = true THEN 1 END) as with_forms,
                COUNT(CASE WHEN has_captcha = true THEN 1 END) as with_captcha,
                COUNT(CASE WHEN requires_proxy = true THEN 1 END) as requires_proxy
            FROM websites 
            WHERE campaign_id = :campaign_id
        """
        )

        stats_result = (
            db.execute(stats_query, {"campaign_id": campaign_id}).mappings().all()
        )

        # Process results
        stats = {}
        for row in stats_result:
            stats[row["status"]] = {
                "count": row["count"],
                "with_forms": row["with_forms"],
                "with_captcha": row["with_captcha"],
                "requires_proxy": row["requires_proxy"],
            }

        # Only log if high failure rate
        total_count = stats.get("total", {}).get("count", 0)
        failed_count = stats.get("failed", {}).get("count", 0)

        if total_count > 0 and (failed_count / total_count) > 0.3:
            logger.warning(
                "High website failure rate",
                extra={
                    "campaign_id": campaign_id,
                    "total_websites": total_count,
                    "failed_websites": failed_count,
                    "failure_rate": round((failed_count / total_count) * 100, 2),
                },
            )

        return {"stats": stats}

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        logger.error(
            "Database error retrieving website stats",
            extra={
                "campaign_id": campaign_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve website statistics",
        )
