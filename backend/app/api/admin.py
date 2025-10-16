# app/api/admin.py - Fixed version without Request parameters
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User

from app.logging import get_logger, log_function, log_exceptions
from app.logging.core import user_id_var

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = get_logger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"], redirect_slashes=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


# Safe schema imports with fallbacks
try:
    from app.schemas.admin import SystemStatus, UserManagement, AdminResponse
except ImportError:
    from pydantic import BaseModel

    class SystemStatus(BaseModel):
        status: str
        database: str
        services: Dict[str, str]
        timestamp: str

    class UserManagement(BaseModel):
        user_id: str
        action: str
        reason: Optional[str] = None

    class AdminResponse(BaseModel):
        success: bool
        message: str
        data: Optional[Dict[str, Any]] = None


class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    role: str = "user"
    password: str


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@log_exceptions("check_admin_access")
def check_admin_access(current_user: User) -> bool:
    """Check if user has admin access"""
    try:
        role = getattr(current_user, "role", "user")
        if hasattr(role, "value"):
            role_str = str(role.value).lower()
        else:
            role_str = str(role).lower()

        has_access = role_str in ["admin", "owner", "superuser"]

        logger.auth_event(
            action="admin_access_check",
            email=current_user.email,
            success=has_access,
        )

        return has_access
    except Exception as e:
        logger.exception(e, handled=True)
        return False


def require_admin_access(current_user: User):
    """Require admin access or raise 403"""
    if not check_admin_access(current_user):
        logger.warning(
            "Admin access denied",
            context={"attempted_action": "admin_access"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


@router.get("/system-status")
@log_function("get_system_status")
async def get_system_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get system status - admin only"""
    user_id_var.set(str(current_user.id))
    require_admin_access(current_user)

    try:
        # Test database connection
        db_start = time.time()
        db.execute(text("SELECT 1"))
        db_time = (time.time() - db_start) * 1000

        logger.database_operation(
            operation="HEALTH_CHECK",
            table="system",
            duration_ms=db_time,
            success=True,
        )

        # Check table existence
        try:
            tables_query = text(
                """
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_name IN ('users', 'campaigns', 'submissions', 'websites')
            """
            )
            tables_count = db.execute(tables_query).scalar() or 0

            status_data = {
                "status": "operational" if tables_count >= 4 else "degraded",
                "database": "connected",
                "response_time_ms": round(db_time, 2),
                "tables_available": int(tables_count),
                "services": {
                    "auth": "running",
                    "campaigns": "running",
                    "submissions": "running",
                },
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception:
            status_data = {
                "status": "degraded",
                "database": "connected",
                "response_time_ms": round(db_time, 2),
                "services": {
                    "auth": "unknown",
                    "campaigns": "unknown",
                    "submissions": "unknown",
                },
                "timestamp": datetime.utcnow().isoformat(),
            }

        return status_data

    except Exception as e:
        logger.exception(
            e,
            handled=True,
            context={"endpoint": "/admin/system-status"},
        )
        return {
            "status": "error",
            "database": "error",
            "services": {"auth": "unknown", "campaigns": "unknown"},
            "timestamp": datetime.utcnow().isoformat(),
        }


@router.get("/users")
@log_function("get_all_users")
async def get_all_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    active_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all users with pagination - admin only"""
    user_id_var.set(str(current_user.id))
    require_admin_access(current_user)

    try:
        query_start = time.time()

        base_query = """
            SELECT 
                id, email, first_name, last_name, role, 
                is_active, is_verified, created_at, updated_at
            FROM users
        """
        count_query = "SELECT COUNT(*) FROM users"
        params = {}

        if active_only:
            base_query += " WHERE is_active = true"
            count_query += " WHERE is_active = true"

        total = db.execute(text(count_query), params).scalar() or 0

        offset = (page - 1) * per_page
        paginated_query = (
            f"{base_query} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        )
        params.update({"limit": per_page, "offset": offset})

        users_result = db.execute(text(paginated_query), params).mappings().all()

        users = []
        for user_row in users_result:
            user_dict = {
                "id": str(user_row["id"]),
                "email": user_row["email"],
                "first_name": user_row.get("first_name"),
                "last_name": user_row.get("last_name"),
                "role": user_row.get("role", "user"),
                "is_active": user_row.get("is_active", True),
                "is_verified": user_row.get("is_verified", False),
                "created_at": (
                    user_row["created_at"].isoformat()
                    if user_row.get("created_at")
                    else None
                ),
            }
            users.append(user_dict)

        query_time = (time.time() - query_start) * 1000

        logger.database_operation(
            operation="SELECT",
            table="users",
            duration_ms=query_time,
            affected_rows=len(users),
            success=True,
            page=page,
            total=total,
        )

        return {
            "users": users,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        }

    except Exception as e:
        logger.exception(
            e,
            handled=False,
            context={"endpoint": "/admin/users"},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch users",
        )


@router.post("/users")
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new user - admin only"""
    user_id_var.set(str(current_user.id))
    require_admin_access(current_user)

    try:
        # Check if user already exists
        existing_user = db.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user_data.email},
        ).first()

        if existing_user:
            logger.warning(
                "User creation failed - email exists",
                context={"attempted_email": user_data.email},
            )
            raise HTTPException(
                status_code=400,
                detail="User with this email already exists",
            )

        hashed_password = hash_password(user_data.password)

        create_start = time.time()
        create_query = text(
            """
            INSERT INTO users (first_name, last_name, email, role, hashed_password, is_active, is_verified)
            VALUES (:first_name, :last_name, :email, :role, :hashed_password, true, true)
            RETURNING id
        """
        )

        result = db.execute(
            create_query,
            {
                "first_name": user_data.first_name,
                "last_name": user_data.last_name,
                "email": user_data.email,
                "role": user_data.role,
                "hashed_password": hashed_password,
            },
        ).first()

        db.commit()
        create_time = (time.time() - create_start) * 1000

        logger.database_operation(
            operation="INSERT",
            table="users",
            duration_ms=create_time,
            affected_rows=1,
            success=True,
        )

        logger.auth_event(
            action="user_created",
            email=user_data.email,
            success=True,
        )

        return {
            "id": str(result.id),
            "message": "User created successfully",
            "email": user_data.email,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(
            e,
            handled=False,
            context={"endpoint": "/admin/users"},
        )
        raise HTTPException(status_code=500, detail="Error creating user")


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a user - admin only"""
    user_id_var.set(str(current_user.id))
    require_admin_access(current_user)

    updated_fields = [
        k for k, v in user_data.model_dump(exclude_unset=True).items() if v is not None
    ]

    try:
        # Check if user exists
        existing_user = db.execute(
            text("SELECT id, email FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        ).first()

        if not existing_user:
            logger.warning(
                "User update failed - user not found",
                context={"target_user_id": user_id},
            )
            raise HTTPException(status_code=404, detail="User not found")

        update_start = time.time()
        update_fields = []
        params = {"user_id": user_id}

        if user_data.first_name is not None:
            update_fields.append("first_name = :first_name")
            params["first_name"] = user_data.first_name

        if user_data.last_name is not None:
            update_fields.append("last_name = :last_name")
            params["last_name"] = user_data.last_name

        if user_data.email is not None:
            update_fields.append("email = :email")
            params["email"] = user_data.email

        if user_data.role is not None:
            update_fields.append("role = :role")
            params["role"] = user_data.role

        if user_data.is_active is not None:
            update_fields.append("is_active = :is_active")
            params["is_active"] = user_data.is_active

        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")

        update_query = text(
            f"""
            UPDATE users 
            SET {', '.join(update_fields)}, updated_at = NOW()
            WHERE id = :user_id
        """
        )

        db.execute(update_query, params)
        db.commit()

        update_time = (time.time() - update_start) * 1000

        logger.database_operation(
            operation="UPDATE",
            table="users",
            duration_ms=update_time,
            affected_rows=1,
            success=True,
        )

        return {"message": "User updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(
            e,
            handled=False,
            context={"endpoint": f"/admin/users/{user_id}"},
        )
        raise HTTPException(status_code=500, detail="Error updating user")


@router.delete("/users/{user_id}")
@log_function("delete_user")
async def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a user - admin only"""
    user_id_var.set(str(current_user.id))
    require_admin_access(current_user)

    if str(current_user.id) == user_id:
        logger.warning(
            "Admin attempted self-deletion",
            context={"attempted_target": user_id},
        )
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    try:
        # Check if user exists
        existing_user = db.execute(
            text("SELECT id, email FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        ).first()

        if not existing_user:
            logger.warning(
                "User deletion failed - user not found",
                context={"target_user_id": user_id},
            )
            raise HTTPException(status_code=404, detail="User not found")

        delete_start = time.time()
        delete_query = text("DELETE FROM users WHERE id = :user_id")
        db.execute(delete_query, {"user_id": user_id})
        db.commit()

        delete_time = (time.time() - delete_start) * 1000

        logger.database_operation(
            operation="DELETE",
            table="users",
            duration_ms=delete_time,
            affected_rows=1,
            success=True,
        )

        logger.auth_event(
            action="user_deleted",
            email=existing_user.email,
            success=True,
        )

        return {"message": "User deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(
            e,
            handled=False,
            context={"endpoint": f"/admin/users/{user_id}"},
        )
        raise HTTPException(status_code=500, detail="Error deleting user")


@router.get("/metrics")
@log_function("get_system_metrics")
async def get_system_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed system metrics - admin only"""
    user_id_var.set(str(current_user.id))
    require_admin_access(current_user)

    try:
        metrics_start = time.time()

        metrics_query = text(
            """
            SELECT 
                (SELECT COUNT(*) FROM users) as total_users,
                (SELECT COUNT(*) FROM users WHERE is_active = true) as active_users,
                (SELECT COUNT(*) FROM users WHERE is_verified = true) as verified_users,
                (SELECT COUNT(*) FROM users WHERE role IN ('admin', 'owner')) as admin_users,
                (SELECT COUNT(*) FROM campaigns) as total_campaigns,
                (SELECT COUNT(*) FROM campaigns WHERE status IN ('ACTIVE', 'running')) as active_campaigns,
                (SELECT COUNT(*) FROM submissions) as total_submissions,
                (SELECT COUNT(*) FROM submissions WHERE success = true) as successful_submissions,
                (SELECT COUNT(*) FROM submissions WHERE captcha_encountered = true) as captcha_submissions,
                (SELECT COUNT(*) FROM websites) as total_websites,
                (SELECT COUNT(*) FROM websites WHERE form_detected = true) as websites_with_forms,
                (SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days') as new_users_week,
                (SELECT COUNT(*) FROM campaigns WHERE created_at >= NOW() - INTERVAL '24 hours') as campaigns_today,
                (SELECT COUNT(*) FROM submissions WHERE created_at >= NOW() - INTERVAL '24 hours') as submissions_today
        """
        )

        result = db.execute(metrics_query).mappings().first() or {}
        metrics_time = (time.time() - metrics_start) * 1000

        logger.database_operation(
            operation="AGGREGATE",
            table="metrics",
            duration_ms=metrics_time,
            success=True,
        )

        total_users = int(result.get("total_users", 0) or 0)
        active_users = int(result.get("active_users", 0) or 0)
        total_submissions = int(result.get("total_submissions", 0) or 0)
        successful_submissions = int(result.get("successful_submissions", 0) or 0)

        user_activity_rate = (
            (active_users / total_users * 100) if total_users > 0 else 0
        )
        submission_success_rate = (
            (successful_submissions / total_submissions * 100)
            if total_submissions > 0
            else 0
        )

        metrics = {
            "users": {
                "total": total_users,
                "active": active_users,
                "verified": int(result.get("verified_users", 0) or 0),
                "admins": int(result.get("admin_users", 0) or 0),
                "new_this_week": int(result.get("new_users_week", 0) or 0),
                "activity_rate": round(user_activity_rate, 2),
            },
            "campaigns": {
                "total": int(result.get("total_campaigns", 0) or 0),
                "active": int(result.get("active_campaigns", 0) or 0),
                "today": int(result.get("campaigns_today", 0) or 0),
            },
            "submissions": {
                "total": total_submissions,
                "successful": successful_submissions,
                "with_captcha": int(result.get("captcha_submissions", 0) or 0),
                "success_rate": round(submission_success_rate, 2),
                "today": int(result.get("submissions_today", 0) or 0),
            },
            "websites": {
                "total": int(result.get("total_websites", 0) or 0),
                "with_forms": int(result.get("websites_with_forms", 0) or 0),
            },
            "system": {
                "status": "healthy",
                "query_time_ms": round(metrics_time, 2),
            },
        }

        return metrics

    except Exception as e:
        logger.exception(
            e,
            handled=True,
            context={"endpoint": "/admin/metrics"},
        )
        return {
            "users": {"total": 0, "active": 0, "activity_rate": 0},
            "campaigns": {"total": 0, "active": 0},
            "submissions": {"total": 0, "successful": 0, "success_rate": 0},
            "websites": {"total": 0},
            "system": {"status": "error"},
        }
