# app/api/settings.py - User settings management with optimized logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime
import json

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.logging import get_logger, log_function
from app.logging.core import request_id_var, user_id_var

logger = get_logger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])

# Default settings template
DEFAULT_SETTINGS = {
    "notifications": {
        "email": True,
        "push": True,
        "campaign_complete": True,
        "campaign_failed": True,
        "weekly_report": True,
    },
    "display": {
        "theme": "light",
        "timezone": "UTC",
        "language": "en",
        "items_per_page": 25,
    },
    "automation": {
        "max_retries": 3,
        "timeout_seconds": 30,
        "parallel_processing": False,
        "auto_restart_failed": False,
    },
    "privacy": {
        "share_analytics": False,
        "public_profile": False,
    },
}


class NotificationSettings(BaseModel):
    email: bool = True
    push: bool = True
    campaign_complete: bool = True
    campaign_failed: bool = True
    weekly_report: bool = True


class DisplaySettings(BaseModel):
    theme: str = Field(default="light", regex="^(light|dark|auto)$")
    timezone: str = "UTC"
    language: str = Field(default="en", regex="^[a-z]{2}$")
    items_per_page: int = Field(default=25, ge=10, le=100)


class AutomationSettings(BaseModel):
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=30, ge=10, le=300)
    parallel_processing: bool = False
    auto_restart_failed: bool = False


class PrivacySettings(BaseModel):
    share_analytics: bool = False
    public_profile: bool = False


class UserSettings(BaseModel):
    notifications: NotificationSettings
    display: DisplaySettings
    automation: AutomationSettings
    privacy: PrivacySettings


class SettingsUpdate(BaseModel):
    section: str
    settings: Dict[str, Any]

    @validator("section")
    def validate_section(cls, v):
        valid_sections = ["notifications", "display", "automation", "privacy"]
        if v not in valid_sections:
            raise ValueError(f"Section must be one of {valid_sections}")
        return v


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


@router.get("/", response_model=UserSettings)
@log_function("get_user_settings")
async def get_user_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get user settings"""
    user_id_var.set(str(current_user.id))

    try:
        query = text(
            """
            SELECT settings FROM user_settings 
            WHERE user_id = :user_id
        """
        )

        result = db.execute(query, {"user_id": str(current_user.id)}).scalar()

        if result:
            settings = json.loads(result) if isinstance(result, str) else result
        else:
            # Create default settings if none exist
            settings = DEFAULT_SETTINGS.copy()

            insert_query = text(
                """
                INSERT INTO user_settings (user_id, settings, created_at, updated_at)
                VALUES (:user_id, :settings, :created_at, :updated_at)
                ON CONFLICT (user_id) DO NOTHING
            """
            )

            db.execute(
                insert_query,
                {
                    "user_id": str(current_user.id),
                    "settings": json.dumps(settings),
                    "created_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            )
            db.commit()

        # No logging for routine settings retrieval
        return UserSettings(**settings)

    except Exception as e:
        logger.error(
            "Failed to get user settings",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": str(current_user.id),
            },
            exc_info=True,
        )
        # Return defaults on error
        return UserSettings(**DEFAULT_SETTINGS)


@router.put("/", response_model=UserSettings)
@log_function("update_user_settings")
async def update_user_settings(
    request: Request,
    settings_update: UserSettings,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update all user settings"""
    user_id_var.set(str(current_user.id))

    try:
        settings_dict = settings_update.dict()

        update_query = text(
            """
            INSERT INTO user_settings (user_id, settings, created_at, updated_at)
            VALUES (:user_id, :settings, :created_at, :updated_at)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                settings = :settings,
                updated_at = :updated_at
        """
        )

        db.execute(
            update_query,
            {
                "user_id": str(current_user.id),
                "settings": json.dumps(settings_dict),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )

        db.commit()

        # Log only significant settings changes
        if (
            settings_dict.get("privacy", {}).get("share_analytics")
            != DEFAULT_SETTINGS["privacy"]["share_analytics"]
        ):
            logger.info(
                "Privacy settings changed",
                extra={
                    "user_id": str(current_user.id),
                    "share_analytics": settings_dict["privacy"]["share_analytics"],
                    "ip": get_client_ip(request),
                },
            )

        return settings_update

    except Exception as e:
        logger.error(
            "Failed to update user settings",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": str(current_user.id),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update settings")


@router.patch("/{section}")
@log_function("update_settings_section")
async def update_settings_section(
    request: Request,
    section: str,
    section_settings: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a specific section of user settings"""
    user_id_var.set(str(current_user.id))

    valid_sections = ["notifications", "display", "automation", "privacy"]
    if section not in valid_sections:
        raise HTTPException(
            status_code=400, detail=f"Invalid section. Must be one of {valid_sections}"
        )

    try:
        # Get current settings
        query = text(
            """
            SELECT settings FROM user_settings 
            WHERE user_id = :user_id
        """
        )

        result = db.execute(query, {"user_id": str(current_user.id)}).scalar()

        if result:
            current_settings = json.loads(result) if isinstance(result, str) else result
        else:
            current_settings = DEFAULT_SETTINGS.copy()

        # Update the specific section
        current_settings[section] = {
            **current_settings.get(section, {}),
            **section_settings,
        }

        # Save updated settings
        update_query = text(
            """
            INSERT INTO user_settings (user_id, settings, created_at, updated_at)
            VALUES (:user_id, :settings, :created_at, :updated_at)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                settings = :settings,
                updated_at = :updated_at
        """
        )

        db.execute(
            update_query,
            {
                "user_id": str(current_user.id),
                "settings": json.dumps(current_settings),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )

        db.commit()

        # Log security-relevant changes only
        if section == "privacy":
            logger.info(
                "Privacy settings updated",
                extra={
                    "user_id": str(current_user.id),
                    "section": section,
                    "ip": get_client_ip(request),
                },
            )
        elif section == "automation" and section_settings.get("parallel_processing"):
            logger.info(
                "Parallel processing enabled",
                extra={
                    "user_id": str(current_user.id),
                    "ip": get_client_ip(request),
                },
            )

        return {
            "success": True,
            "section": section,
            "settings": current_settings[section],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update settings section",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": str(current_user.id),
                "section": section,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to update settings section")


@router.post("/reset")
@log_function("reset_settings")
async def reset_settings(
    request: Request,
    section: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset settings to defaults"""
    user_id_var.set(str(current_user.id))

    try:
        if section:
            # Reset specific section
            valid_sections = ["notifications", "display", "automation", "privacy"]
            if section not in valid_sections:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid section. Must be one of {valid_sections}",
                )

            # Get current settings
            query = text(
                """
                SELECT settings FROM user_settings 
                WHERE user_id = :user_id
            """
            )

            result = db.execute(query, {"user_id": str(current_user.id)}).scalar()

            if result:
                current_settings = (
                    json.loads(result) if isinstance(result, str) else result
                )
            else:
                current_settings = DEFAULT_SETTINGS.copy()

            # Reset the section
            current_settings[section] = DEFAULT_SETTINGS[section].copy()
            settings_to_save = current_settings
        else:
            # Reset all settings
            settings_to_save = DEFAULT_SETTINGS.copy()

        # Save reset settings
        update_query = text(
            """
            INSERT INTO user_settings (user_id, settings, created_at, updated_at)
            VALUES (:user_id, :settings, :created_at, :updated_at)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                settings = :settings,
                updated_at = :updated_at
        """
        )

        db.execute(
            update_query,
            {
                "user_id": str(current_user.id),
                "settings": json.dumps(settings_to_save),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )

        db.commit()

        # Log settings reset for audit
        logger.info(
            "Settings reset to defaults",
            extra={
                "user_id": str(current_user.id),
                "section": section or "all",
                "ip": get_client_ip(request),
            },
        )

        return {
            "success": True,
            "message": f"Settings reset to defaults",
            "section": section or "all",
            "settings": settings_to_save,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to reset settings",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": str(current_user.id),
                "section": section,
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to reset settings")


@router.get("/export")
async def export_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export user settings as JSON"""
    user_id_var.set(str(current_user.id))

    try:
        query = text(
            """
            SELECT settings FROM user_settings 
            WHERE user_id = :user_id
        """
        )

        result = db.execute(query, {"user_id": str(current_user.id)}).scalar()

        if result:
            settings = json.loads(result) if isinstance(result, str) else result
        else:
            settings = DEFAULT_SETTINGS.copy()

        # No logging for exports
        return {
            "success": True,
            "settings": settings,
            "exported_at": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(
            "Failed to export settings",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "user_id": str(current_user.id),
            },
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Failed to export settings")
