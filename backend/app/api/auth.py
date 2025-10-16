# app/api/auth.py - Fixed authentication without decorator issues
from __future__ import annotations

import os
import time
import uuid
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from functools import wraps

from fastapi import APIRouter, Depends, HTTPException, Request, status, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.models.user import User
from app.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    verify_token,
    JWT_SECRET,
    JWT_ALGORITHM,
    JWT_EXPIRATION_HOURS,
)
from app.core.dependencies import get_current_user

# Import logging but we'll temporarily disable the decorators
from app.logging import get_logger
from app.logging.core import user_id_var

logger = get_logger(__name__)
router = APIRouter(tags=["auth"], redirect_slashes=False)
security = HTTPBearer()

# Auth configuration
ALLOW_UNVERIFIED_LOGIN = os.getenv("AUTH_ALLOW_UNVERIFIED", "true").lower() == "true"
ALLOW_INACTIVE_LOGIN = os.getenv("AUTH_ALLOW_INACTIVE", "false").lower() == "true"

# Token storage (use Redis in production)
RESET_TOKENS = {}
VERIFICATION_TOKENS = {}


# ============ REQUEST/RESPONSE MODELS ============


class RegisterRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="User password")
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    company_name: Optional[str] = Field(default=None, max_length=255)
    job_title: Optional[str] = Field(default=None, max_length=255)
    phone_number: Optional[str] = Field(default=None, max_length=50)
    website_url: Optional[str] = Field(default=None, max_length=500)

    @validator("email")
    def validate_email(cls, v):
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format")
        return v.lower().strip()


class LoginRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=1, description="User password")

    @validator("email")
    def validate_email(cls, v):
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, v):
            raise ValueError("Invalid email format")
        return v.lower().strip()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    first_name: Optional[str]
    last_name: Optional[str]
    role: str
    is_active: bool
    is_verified: bool
    created_at: Optional[datetime]


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class EmailVerificationRequest(BaseModel):
    email: str


def get_client_ip(request: Request) -> str:
    """Extract client IP from request"""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


# Simple logging wrapper that preserves function signature
def log_auth_event(action: str):
    """Simple decorator that preserves function signature"""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                logger.info(f"Auth action started: {action}")
                result = await func(*args, **kwargs)
                logger.info(f"Auth action completed: {action}")
                return result
            except Exception as e:
                logger.error(f"Auth action failed: {action} - {str(e)}")
                raise

        return wrapper

    return decorator


@router.post(
    "/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    payload: RegisterRequest = Body(...),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Register a new user"""
    email = payload.email.lower().strip()
    client_ip = get_client_ip(request) if request else "unknown"

    try:
        # Check if user exists
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            logger.warning(f"Registration failed - email exists: {email}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )

        # Create new user
        user_id = str(uuid.uuid4())
        user = User(
            id=user_id,
            email=email,
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            is_active=True,
            is_verified=False,
            role="user",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        db.add(user)

        # Create user profile if additional data provided
        if any(
            [
                payload.company_name,
                payload.job_title,
                payload.phone_number,
                payload.website_url,
            ]
        ):
            try:
                db.execute(
                    text(
                        """
                        INSERT INTO user_profiles (
                            user_id, company_name, job_title, phone_number, website_url,
                            created_at, updated_at
                        ) VALUES (
                            :user_id, :company_name, :job_title, :phone_number, :website_url,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                    """
                    ),
                    {
                        "user_id": user_id,
                        "company_name": payload.company_name,
                        "job_title": payload.job_title,
                        "phone_number": payload.phone_number,
                        "website_url": payload.website_url,
                    },
                )
            except Exception:
                pass

        # Create default settings
        try:
            db.execute(
                text(
                    """
                    INSERT INTO settings (id, user_id, auto_submit, created_at, updated_at)
                    VALUES (gen_random_uuid(), :user_id, false, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
                ),
                {"user_id": user_id},
            )
        except Exception:
            pass

        db.commit()

        token = create_access_token(data={"sub": email, "user_id": user_id})

        logger.info(f"User registered successfully: {email} from IP: {client_ip}")

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=JWT_EXPIRATION_HOURS * 3600,
            user={
                "id": user_id,
                "email": email,
                "first_name": payload.first_name,
                "last_name": payload.last_name,
                "is_active": True,
                "is_verified": False,
                "role": "user",
            },
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Registration failed for {email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed",
        )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest = Body(...),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """Login user"""
    email = payload.email.lower().strip()
    client_ip = get_client_ip(request) if request else "unknown"

    try:
        # Find user
        user = db.query(User).filter(User.email == email).first()

        if not user:
            logger.warning(
                f"Login failed - user not found: {email} from IP: {client_ip}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Verify password
        if not verify_password(payload.password, user.hashed_password):
            logger.warning(
                f"Login failed - invalid password: {email} from IP: {client_ip}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Check account status
        if not ALLOW_INACTIVE_LOGIN and not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )

        if not ALLOW_UNVERIFIED_LOGIN and not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email to login",
            )

        # Generate token
        token = create_access_token(data={"sub": email, "user_id": str(user.id)})

        user_id_var.set(str(user.id))

        logger.info(f"User logged in successfully: {email} from IP: {client_ip}")

        return TokenResponse(
            access_token=token,
            token_type="bearer",
            expires_in=JWT_EXPIRATION_HOURS * 3600,
            user={
                "id": str(user.id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_active": user.is_active,
                "is_verified": user.is_verified,
                "role": user.role or "user",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed for {email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current user information"""
    user_id_var.set(str(current_user.id))

    try:
        # Get user profile if exists
        profile = None
        try:
            profile_result = db.execute(
                text("SELECT * FROM user_profiles WHERE user_id = :user_id"),
                {"user_id": str(current_user.id)},
            ).first()

            if profile_result:
                profile = dict(profile_result._mapping)
        except Exception:
            pass

        # Get subscription info
        subscription = None
        try:
            if current_user.plan_id:
                plan_result = db.execute(
                    text("SELECT * FROM subscription_plans WHERE id = :plan_id"),
                    {"plan_id": str(current_user.plan_id)},
                ).first()

                if plan_result:
                    subscription = dict(plan_result._mapping)
        except Exception:
            pass

        response_data = {
            "id": str(current_user.id),
            "email": current_user.email,
            "first_name": current_user.first_name,
            "last_name": current_user.last_name,
            "role": current_user.role or "user",
            "is_active": current_user.is_active,
            "is_verified": current_user.is_verified,
            "created_at": current_user.created_at,
        }

        if profile:
            response_data["profile"] = {
                "phone_number": profile.get("phone_number"),
                "company_name": profile.get("company_name"),
                "job_title": profile.get("job_title"),
                "website_url": profile.get("website_url"),
            }

        if subscription:
            response_data["subscription"] = {
                "plan_name": subscription.get("name", "Free"),
                "max_websites": subscription.get("max_websites", 10),
            }

        return response_data

    except Exception as e:
        logger.error(f"Failed to fetch user info: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch user info")


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
):
    """Logout user"""
    user_id_var.set(str(current_user.id))
    logger.info(f"User logged out: {current_user.email}")
    return {"success": True, "message": "Logged out successfully"}


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Refresh authentication token"""
    user_id_var.set(str(current_user.id))

    try:
        new_token = create_access_token(
            data={"sub": current_user.email, "user_id": str(current_user.id)}
        )

        return TokenResponse(
            access_token=new_token,
            token_type="bearer",
            expires_in=JWT_EXPIRATION_HOURS * 3600,
            user={
                "id": str(current_user.id),
                "email": current_user.email,
                "first_name": current_user.first_name,
                "last_name": current_user.last_name,
                "is_active": current_user.is_active,
                "is_verified": current_user.is_verified,
                "role": current_user.role or "user",
            },
        )

    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Token refresh failed")


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change user password"""
    user_id_var.set(str(current_user.id))

    try:
        # Verify old password
        if not verify_password(payload.current_password, current_user.hashed_password):
            logger.warning(
                f"Password change failed - invalid current password for user: {current_user.id}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid current password",
            )

        # Update password
        current_user.hashed_password = hash_password(payload.new_password)
        current_user.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"Password changed successfully for user: {current_user.email}")

        return {"success": True, "message": "Password changed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Password change failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Password change failed")


@router.post("/forgot-password")
async def forgot_password(
    payload: PasswordResetRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Request password reset"""
    email = payload.email.lower().strip()

    try:
        user = db.query(User).filter(User.email == email).first()

        if user:
            reset_token = secrets.token_urlsafe(32)
            RESET_TOKENS[reset_token] = {
                "email": email,
                "user_id": str(user.id),
                "created_at": time.time(),
                "expires_at": time.time() + 3600,
            }

            logger.info(f"Password reset requested for: {email}")

        return {
            "success": True,
            "message": "If the email exists, a password reset link has been sent.",
        }

    except Exception as e:
        logger.error(f"Password reset request failed: {str(e)}")
        return {
            "success": True,
            "message": "If the email exists, a password reset link has been sent.",
        }


@router.post("/reset-password")
async def reset_password(
    payload: PasswordResetConfirm = Body(...),
    db: Session = Depends(get_db),
):
    """Reset password with token"""
    try:
        # Validate token
        if payload.token not in RESET_TOKENS:
            raise HTTPException(status_code=400, detail="Invalid or expired token")

        token_data = RESET_TOKENS[payload.token]

        # Check expiration
        if time.time() > token_data["expires_at"]:
            del RESET_TOKENS[payload.token]
            raise HTTPException(status_code=400, detail="Reset token expired")

        # Update password
        user = db.query(User).filter(User.email == token_data["email"]).first()
        if not user:
            raise HTTPException(status_code=400, detail="User not found")

        user.hashed_password = hash_password(payload.new_password)
        user.updated_at = datetime.utcnow()
        db.commit()

        del RESET_TOKENS[payload.token]

        logger.info(f"Password reset successful for: {user.email}")

        return {"success": True, "message": "Password reset successful"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Password reset failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Password reset failed")


@router.post("/verify-email")
async def verify_email(
    token: str,
    db: Session = Depends(get_db),
):
    """Verify email address"""
    try:
        # Validate token
        if token not in VERIFICATION_TOKENS:
            raise HTTPException(status_code=400, detail="Invalid or expired token")

        token_data = VERIFICATION_TOKENS[token]

        # Check expiration
        if time.time() > token_data["expires_at"]:
            del VERIFICATION_TOKENS[token]
            raise HTTPException(status_code=400, detail="Verification token expired")

        # Update user verification status
        user = db.query(User).filter(User.email == token_data["email"]).first()
        if not user:
            raise HTTPException(status_code=400, detail="User not found")

        user.is_verified = True
        user.updated_at = datetime.utcnow()
        db.commit()

        del VERIFICATION_TOKENS[token]

        logger.info(f"Email verified successfully for: {user.email}")

        return {"success": True, "message": "Email verified successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Email verification failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Email verification failed")


@router.post("/resend-verification")
async def resend_verification(
    payload: EmailVerificationRequest = Body(...),
    db: Session = Depends(get_db),
):
    """Resend email verification"""
    email = payload.email.lower().strip()

    try:
        user = db.query(User).filter(User.email == email).first()

        if user and not user.is_verified:
            verification_token = secrets.token_urlsafe(32)
            VERIFICATION_TOKENS[verification_token] = {
                "email": email,
                "user_id": str(user.id),
                "created_at": time.time(),
                "expires_at": time.time() + 86400,
            }

        return {
            "success": True,
            "message": "If the email exists and is unverified, a verification email has been sent.",
        }

    except Exception as e:
        logger.error(f"Resend verification failed: {str(e)}")
        return {
            "success": True,
            "message": "If the email exists and is unverified, a verification email has been sent.",
        }


@router.get("/health")
async def health_check():
    """Auth service health check"""
    return {
        "status": "healthy",
        "service": "auth",
        "timestamp": datetime.utcnow().isoformat(),
        "features": {
            "allow_unverified_login": ALLOW_UNVERIFIED_LOGIN,
            "allow_inactive_login": ALLOW_INACTIVE_LOGIN,
            "jwt_algorithm": JWT_ALGORITHM,
            "jwt_expiration_hours": JWT_EXPIRATION_HOURS,
        },
    }


# Test endpoint without decorators
@router.post("/test-login")
async def test_login(data: LoginRequest = Body(...)):
    """Test endpoint to verify routing works"""
    return {"received": data.dict(), "message": "Test successful"}
