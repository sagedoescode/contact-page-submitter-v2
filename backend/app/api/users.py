# app/api/users.py - Fixed version without decorator issues
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    File,
    UploadFile,
)

from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.log_service import LogService as ApplicationInsightsLogger
from app.logging import get_logger
from app.logging.core import user_id_var

# Initialize structured logger
logger = get_logger(__name__)

router = APIRouter(tags=["users"], redirect_slashes=False)


class ProfileUpdateRequest(BaseModel):
    # Basic Information
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    phone_number: Optional[str] = Field(None, max_length=20)

    # Company Information
    company_name: Optional[str] = Field(None, max_length=200)
    job_title: Optional[str] = Field(None, max_length=100)
    website_url: Optional[str] = Field(None, max_length=500)
    linkedin_url: Optional[str] = Field(None, max_length=500)
    industry: Optional[str] = Field(None, max_length=100)

    # Location Information
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    zip_code: Optional[str] = Field(None, max_length=20)
    country: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field(None, max_length=50)
    region: Optional[str] = Field(None, max_length=100)

    # Contact Preferences
    preferred_language: Optional[str] = Field(None, max_length=10)
    language: Optional[str] = Field(None, max_length=50)
    preferred_contact: Optional[str] = Field(None, max_length=100)
    best_time_to_contact: Optional[str] = Field(None, max_length=100)

    # Message Defaults
    subject: Optional[str] = Field(None, max_length=500)
    message: Optional[str] = Field(None)

    # Business Information
    product_interest: Optional[str] = Field(None, max_length=255)
    budget_range: Optional[str] = Field(None, max_length=100)
    referral_source: Optional[str] = Field(None, max_length=255)
    contact_source: Optional[str] = Field(None, max_length=255)
    is_existing_customer: Optional[bool] = Field(None)

    # Additional Fields
    notes: Optional[str] = Field(None)
    form_custom_field_1: Optional[str] = Field(None, max_length=500)
    form_custom_field_2: Optional[str] = Field(None, max_length=500)
    form_custom_field_3: Optional[str] = Field(None, max_length=500)

    # Death By Captcha Credentials
    dbc_username: Optional[str] = Field(None, max_length=255)
    dbc_password: Optional[str] = Field(None, max_length=255)


class UserProfileResponse(BaseModel):
    user: Dict[str, Any]
    profile: Dict[str, Any]


def _get_role_string(user: User) -> str:
    """Helper function to extract role as string"""
    role = getattr(user, "role", "user")
    if hasattr(role, "value"):
        return str(role.value)
    return str(role)


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get user profile combining base user data and extended profile information"""
    user_id_var.set(str(current_user.id))

    try:
        # Build base user data
        base = {
            "id": str(current_user.id),
            "email": current_user.email,
            "first_name": getattr(current_user, "first_name", None),
            "last_name": getattr(current_user, "last_name", None),
            "role": _get_role_string(current_user),
            "is_active": getattr(current_user, "is_active", True),
            "is_verified": getattr(current_user, "is_verified", True),
            "profile_image_url": getattr(current_user, "profile_image_url", None),
            "created_at": (
                current_user.created_at.isoformat()
                if hasattr(current_user, "created_at") and current_user.created_at
                else None
            ),
            "updated_at": (
                current_user.updated_at.isoformat()
                if hasattr(current_user, "updated_at") and current_user.updated_at
                else None
            ),
        }

        # Get extended profile information
        profile_query = text(
            """
            SELECT
                up.phone_number, up.company_name, 
                up.job_title, up.website_url, up.linkedin_url, up.industry, 
                up.city, up.state, up.zip_code, up.country, up.region, 
                up.timezone, up.subject, up.message, up.product_interest,
                up.budget_range, up.referral_source, up.preferred_contact, 
                up.best_time_to_contact, up.contact_source, up.is_existing_customer, 
                up.language, up.preferred_language, up.notes, 
                up.form_custom_field_1, up.form_custom_field_2, up.form_custom_field_3,
                up.dbc_username, 
                CASE 
                    WHEN up.dbc_password IS NOT NULL AND up.dbc_password != '' 
                    THEN '********' 
                    ELSE NULL 
                END as dbc_password_masked,
                CASE 
                    WHEN up.dbc_username IS NOT NULL AND up.dbc_password IS NOT NULL 
                    THEN true 
                    ELSE false 
                END as has_dbc_credentials,
                up.created_at, up.updated_at
            FROM user_profiles up
            WHERE up.user_id = :uid
            LIMIT 1
        """
        )

        profile_result = (
            db.execute(profile_query, {"uid": str(current_user.id)}).mappings().first()
        )

        profile = dict(profile_result) if profile_result else {}

        # Convert datetime objects to ISO strings in profile
        for key, value in profile.items():
            if hasattr(value, "isoformat"):
                profile[key] = value.isoformat()

        # Add CAPTCHA status if DBC credentials exist
        captcha_enabled = profile.get("has_dbc_credentials", False)
        if captcha_enabled:
            profile["captcha_enabled"] = True

        return {"user": base, "profile": profile}

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            "Database error retrieving profile",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve profile",
        )
    except Exception as e:
        logger.error(
            "Unexpected error retrieving profile",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve profile",
        )


@router.put("/profile")
async def update_profile(
    profile_data: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update user profile information including DBC credentials"""
    user_id_var.set(str(current_user.id))

    try:
        # Track what fields are being updated
        updated_data = profile_data.model_dump(exclude_unset=True)
        updated_fields = [k for k, v in updated_data.items() if v is not None]

        # Check if DBC credentials are being updated
        updating_dbc = (
            "dbc_username" in updated_fields or "dbc_password" in updated_fields
        )

        # Update base user fields if provided
        user_updated = False
        user_changes = {}

        if profile_data.first_name is not None:
            old_value = getattr(current_user, "first_name", None)
            current_user.first_name = profile_data.first_name.strip()
            user_updated = True
            user_changes["first_name"] = {
                "old": old_value,
                "new": current_user.first_name,
            }

        if profile_data.last_name is not None:
            old_value = getattr(current_user, "last_name", None)
            current_user.last_name = profile_data.last_name.strip()
            user_updated = True
            user_changes["last_name"] = {
                "old": old_value,
                "new": current_user.last_name,
            }

        if user_updated:
            current_user.updated_at = datetime.utcnow()
            db.add(current_user)

        # Check if user profile exists
        profile_exists_query = text(
            """
            SELECT COUNT(*) FROM user_profiles WHERE user_id = :uid
        """
        )
        profile_exists = (
            db.execute(profile_exists_query, {"uid": str(current_user.id)}).scalar() > 0
        )

        # Prepare profile data (excluding user table fields)
        profile_fields = {}
        for field, value in updated_data.items():
            if value is not None and field not in ["first_name", "last_name"]:
                # Don't strip password fields
                if field == "dbc_password":
                    profile_fields[field] = value
                else:
                    profile_fields[field] = (
                        value.strip() if isinstance(value, str) else value
                    )

        if profile_fields:
            if profile_exists:
                # Update existing profile
                update_parts = []
                params = {"uid": str(current_user.id)}

                for field, value in profile_fields.items():
                    update_parts.append(f"{field} = :{field}")
                    params[field] = value

                if update_parts:
                    params["updated_at"] = datetime.utcnow()
                    update_parts.append("updated_at = :updated_at")

                    update_query = text(
                        f"""
                        UPDATE user_profiles 
                        SET {', '.join(update_parts)}
                        WHERE user_id = :uid
                    """
                    )
                    db.execute(update_query, params)
            else:
                # Create new profile
                fields = list(profile_fields.keys()) + [
                    "user_id",
                    "created_at",
                    "updated_at",
                ]
                placeholders = [f":{field}" for field in fields]

                profile_fields.update(
                    {
                        "user_id": str(current_user.id),
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                )

                insert_query = text(
                    f"""
                    INSERT INTO user_profiles ({', '.join(fields)})
                    VALUES ({', '.join(placeholders)})
                """
                )
                db.execute(insert_query, profile_fields)

        db.commit()

        # Only log significant updates
        if updating_dbc:
            logger.info(
                "DBC credentials updated",
                extra={
                    "user_id": str(current_user.id),
                    "has_username": bool(profile_data.dbc_username),
                    "has_password": bool(profile_data.dbc_password),
                },
            )

        # Only log profile creation
        if not profile_exists and profile_fields:
            logger.info(
                "User profile created",
                extra={
                    "user_id": str(current_user.id),
                    "fields_populated": len(profile_fields),
                },
            )

        return {
            "success": True,
            "message": "Profile updated successfully",
            "fields_updated": updated_fields,
            "update_summary": {
                "user_fields": list(user_changes.keys()),
                "profile_fields": list(profile_fields.keys()),
                "profile_created": not profile_exists and bool(profile_fields),
            },
        }

    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            "Database error updating profile",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )
    except Exception as e:
        logger.error(
            "Unexpected error updating profile",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile",
        )


@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Upload user avatar/profile image"""
    user_id_var.set(str(current_user.id))

    # Validate file type
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Read file content first to check size
    file_content = await file.read()

    # Validate file size (5MB limit)
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be less than 5MB")

    try:
        file_extension = (
            file.filename.split(".")[-1]
            if file.filename and "." in file.filename
            else "jpg"
        )
        file_name = f"{current_user.id}_{int(time.time())}.{file_extension}"

        # Create uploads directory if it doesn't exist
        upload_dir = "uploads/avatars"
        os.makedirs(upload_dir, exist_ok=True)

        # Save file locally
        file_path = os.path.join(upload_dir, file_name)
        with open(file_path, "wb") as f:
            f.write(file_content)

        # Generate URL
        profile_image_url = f"/static/{upload_dir}/{file_name}"

        # Update user record
        current_user.profile_image_url = profile_image_url
        current_user.updated_at = datetime.utcnow()
        db.add(current_user)
        db.commit()

        # Log avatar upload for audit
        logger.info(
            "Profile image uploaded",
            extra={
                "user_id": str(current_user.id),
                "file_size": len(file_content),
                "content_type": file.content_type,
            },
        )

        return {
            "profile_image_url": profile_image_url,
            "success": True,
            "file_info": {
                "original_name": file.filename,
                "saved_name": file_name,
                "size_bytes": len(file_content),
                "content_type": file.content_type,
            },
        }

    except Exception as e:
        db.rollback()
        logger.error(
            "Failed to upload avatar",
            extra={
                "user_id": str(current_user.id),
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to upload image")


@router.get("/stats")
async def get_user_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get user statistics and metrics"""
    user_id_var.set(str(current_user.id))

    try:
        # Get campaign statistics
        campaigns_query = text(
            """
            SELECT 
                COUNT(*) as total_campaigns,
                COUNT(CASE WHEN status = 'ACTIVE' THEN 1 END) as active_campaigns,
                COUNT(CASE WHEN status = 'COMPLETED' THEN 1 END) as completed_campaigns,
                COUNT(CASE WHEN status = 'DRAFT' THEN 1 END) as draft_campaigns,
                COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_campaigns
            FROM campaigns WHERE user_id = :user_id
        """
        )

        campaigns_result = (
            db.execute(campaigns_query, {"user_id": str(current_user.id)})
            .mappings()
            .first()
        )

        # Get submission statistics
        submissions_query = text(
            """
            SELECT 
                COUNT(*) as total_submissions,
                COUNT(CASE WHEN status = 'successful' THEN 1 END) as successful_submissions,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_submissions,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_submissions
            FROM submissions s
            JOIN campaigns c ON s.campaign_id = c.id
            WHERE c.user_id = :user_id
        """
        )

        submissions_result = (
            db.execute(submissions_query, {"user_id": str(current_user.id)})
            .mappings()
            .first()
        )

        # Build response
        stats = {
            "user_info": {
                "id": str(current_user.id),
                "email": current_user.email,
                "role": _get_role_string(current_user),
                "is_active": getattr(current_user, "is_active", True),
                "created_at": (
                    current_user.created_at.isoformat()
                    if hasattr(current_user, "created_at") and current_user.created_at
                    else None
                ),
            },
            "campaigns": dict(campaigns_result) if campaigns_result else {},
            "submissions": dict(submissions_result) if submissions_result else {},
            "calculated_metrics": {},
        }

        # Calculate additional metrics
        total_campaigns = stats["campaigns"].get("total_campaigns", 0)
        total_submissions = stats["submissions"].get("total_submissions", 0)
        successful_submissions = stats["submissions"].get("successful_submissions", 0)

        if total_submissions > 0:
            success_rate = (successful_submissions / total_submissions) * 100
            stats["calculated_metrics"]["overall_success_rate"] = round(success_rate, 2)

        if total_campaigns > 0:
            stats["calculated_metrics"]["avg_submissions_per_campaign"] = round(
                total_submissions / total_campaigns, 2
            )

        # Only log if there are concerning metrics
        if stats["campaigns"].get("failed_campaigns", 0) > 5:
            logger.warning(
                "High failed campaign count",
                extra={
                    "user_id": str(current_user.id),
                    "failed_campaigns": stats["campaigns"]["failed_campaigns"],
                    "total_campaigns": total_campaigns,
                },
            )

        return stats

    except SQLAlchemyError as e:
        logger.error(
            "Database error retrieving user stats",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user statistics",
        )
    except Exception as e:
        logger.error(
            "Unexpected error retrieving user stats",
            extra={
                "user_id": str(current_user.id),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve user statistics",
        )
