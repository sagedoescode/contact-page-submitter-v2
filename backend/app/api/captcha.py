"""Enhanced Captcha API endpoints with optimized logging for FastAPI."""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from functools import wraps
import time
from typing import Dict, Any, Optional
import secrets
import random
from datetime import datetime, timedelta

# Import dependencies - adjust based on your actual project structure
try:
    from app.core.dependencies import get_current_user
    from app.logging import get_logger, log_function
    from app.logging.core import request_id_var, user_id_var

    HAS_AUTH = True
except ImportError:
    import logging

    HAS_AUTH = False

    def get_current_user():
        return None

    def get_logger(name):
        return logging.getLogger(name)

    def log_function(name):
        def decorator(func):
            return func

        return decorator


# Initialize logger
logger = get_logger(__name__)

# Create FastAPI router
router = APIRouter(
    prefix="/api/captcha",
    tags=["captcha"],
    responses={404: {"description": "Not found"}},
)

# Simulated captcha storage (in production, use Redis or similar)
CAPTCHA_STORE = {}
CAPTCHA_ATTEMPTS = {}
MAX_ATTEMPTS = 5
CAPTCHA_LIFETIME = 300  # 5 minutes
CLEANUP_INTERVAL = 60  # Clean expired captchas every 60 seconds
last_cleanup = 0


# Pydantic models for request/response
class CaptchaGenerateResponse(BaseModel):
    success: bool
    captcha_id: Optional[str] = None
    challenge: Optional[str] = None
    expires_in: Optional[int] = None
    error: Optional[str] = None


class CaptchaVerifyRequest(BaseModel):
    captcha_id: str
    answer: str


class CaptchaVerifyResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    attempts_remaining: Optional[int] = None


class CaptchaStatsResponse(BaseModel):
    success: bool
    stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


def get_client_ip(request: Request) -> str:
    """Extract client IP from request headers."""
    if not request or not request.client:
        return "unknown"

    # Check for proxied requests
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    return request.client.host


def clean_expired_captchas():
    """Clean up expired captchas from storage."""
    global last_cleanup
    current_time = time.time()

    # Only clean if enough time has passed
    if current_time - last_cleanup < CLEANUP_INTERVAL:
        return 0

    last_cleanup = current_time
    expired = []

    for captcha_id, data in list(CAPTCHA_STORE.items()):
        if current_time - data["created"] > CAPTCHA_LIFETIME:
            expired.append(captcha_id)

    for captcha_id in expired:
        del CAPTCHA_STORE[captcha_id]
        if captcha_id in CAPTCHA_ATTEMPTS:
            del CAPTCHA_ATTEMPTS[captcha_id]

    return len(expired)


@router.post("/generate", response_model=CaptchaGenerateResponse)
@log_function("generate_captcha")
async def generate_captcha(request: Request):
    """Generate a new captcha challenge."""
    try:
        # Clean expired captchas periodically (non-blocking)
        cleaned = clean_expired_captchas()

        # Generate captcha
        captcha_id = secrets.token_urlsafe(32)

        # Simple math captcha for demonstration
        num1 = random.randint(1, 50)
        num2 = random.randint(1, 50)
        operation = random.choice(["+", "-", "*"])

        if operation == "+":
            answer = num1 + num2
            question = f"{num1} + {num2}"
        elif operation == "-":
            answer = num1 - num2
            question = f"{num1} - {num2}"
        else:
            answer = num1 * num2
            question = f"{num1} × {num2}"

        client_ip = get_client_ip(request)

        # Store captcha
        CAPTCHA_STORE[captcha_id] = {
            "answer": str(answer),
            "created": time.time(),
            "ip": client_ip,
            "attempts": 0,
        }

        # Only log if this is a suspicious pattern (rate limiting would catch this)
        # Normal captcha generation doesn't need logging

        return CaptchaGenerateResponse(
            success=True,
            captcha_id=captcha_id,
            challenge=question,
            expires_in=CAPTCHA_LIFETIME,
        )

    except Exception as e:
        logger.error(
            "Failed to generate captcha",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        return CaptchaGenerateResponse(
            success=False, error="Failed to generate captcha"
        )


@router.post("/verify", response_model=CaptchaVerifyResponse)
@log_function("verify_captcha")
async def verify_captcha(data: CaptchaVerifyRequest, request: Request):
    """Verify a captcha response."""
    client_ip = get_client_ip(request)
    captcha_id_short = (
        data.captcha_id[:8] + "..." if len(data.captcha_id) > 8 else data.captcha_id
    )

    try:
        captcha_id = data.captcha_id
        answer = data.answer

        # Check if captcha exists
        if captcha_id not in CAPTCHA_STORE:
            # Log security event - someone trying invalid captcha
            logger.security_event(
                event="captcha_invalid_attempt",
                severity="warning",
                properties={
                    "captcha_id": captcha_id_short,
                    "ip": client_ip,
                },
            )
            raise HTTPException(status_code=400, detail="Invalid or expired captcha")

        captcha_data = CAPTCHA_STORE[captcha_id]

        # Check expiration
        if time.time() - captcha_data["created"] > CAPTCHA_LIFETIME:
            del CAPTCHA_STORE[captcha_id]
            if captcha_id in CAPTCHA_ATTEMPTS:
                del CAPTCHA_ATTEMPTS[captcha_id]

            raise HTTPException(status_code=400, detail="Captcha expired")

        # Track attempts
        if captcha_id not in CAPTCHA_ATTEMPTS:
            CAPTCHA_ATTEMPTS[captcha_id] = 0

        CAPTCHA_ATTEMPTS[captcha_id] += 1
        current_attempts = CAPTCHA_ATTEMPTS[captcha_id]

        # Check attempt limit
        if current_attempts > MAX_ATTEMPTS:
            del CAPTCHA_STORE[captcha_id]
            del CAPTCHA_ATTEMPTS[captcha_id]

            # Log security event - brute force attempt
            logger.security_event(
                event="captcha_brute_force",
                severity="error",
                properties={
                    "captcha_id": captcha_id_short,
                    "ip": client_ip,
                    "attempts": current_attempts,
                },
            )

            raise HTTPException(status_code=429, detail="Too many attempts")

        # Verify answer
        if str(answer) == str(captcha_data["answer"]):
            # Remove used captcha
            del CAPTCHA_STORE[captcha_id]
            if captcha_id in CAPTCHA_ATTEMPTS:
                del CAPTCHA_ATTEMPTS[captcha_id]

            # Only log failed attempts or suspicious successes
            if current_attempts > 2:
                logger.security_event(
                    event="captcha_verified_after_retries",
                    severity="info",
                    properties={
                        "captcha_id": captcha_id_short,
                        "attempts": current_attempts,
                        "ip": client_ip,
                    },
                )

            return CaptchaVerifyResponse(success=True, message="Captcha verified")
        else:
            # Log if multiple failed attempts (potential bot)
            if current_attempts >= 3:
                logger.security_event(
                    event="captcha_multiple_failures",
                    severity="warning",
                    properties={
                        "captcha_id": captcha_id_short,
                        "attempts": current_attempts,
                        "ip": client_ip,
                    },
                )

            return CaptchaVerifyResponse(
                success=False,
                error="Incorrect answer",
                attempts_remaining=MAX_ATTEMPTS - current_attempts,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Captcha verification error",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
                "ip": client_ip,
            },
            exc_info=True,
        )
        return CaptchaVerifyResponse(success=False, error="Verification failed")


@router.get("/stats", response_model=CaptchaStatsResponse)
@log_function("get_captcha_stats")
async def get_captcha_stats(
    request: Request,
    current_user: Optional[Dict] = Depends(get_current_user) if HAS_AUTH else None,
):
    """Get captcha statistics (admin only)."""
    try:
        # Check admin permission
        if HAS_AUTH and current_user:
            user_id_var.set(str(current_user.get("id")))

            # Implement your admin check here
            # if not is_admin(current_user.get("id")):
            #     raise HTTPException(status_code=403, detail="Unauthorized")

        stats = {
            "active_captchas": len(CAPTCHA_STORE),
            "pending_verifications": len(CAPTCHA_ATTEMPTS),
            "total_attempts": sum(CAPTCHA_ATTEMPTS.values()),
            "max_attempts_allowed": MAX_ATTEMPTS,
            "captcha_lifetime_seconds": CAPTCHA_LIFETIME,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Calculate additional metrics
        if CAPTCHA_ATTEMPTS:
            avg_attempts = sum(CAPTCHA_ATTEMPTS.values()) / len(CAPTCHA_ATTEMPTS)
            stats["average_attempts_per_captcha"] = round(avg_attempts, 2)

        # Only log admin access for audit trail
        if current_user:
            logger.auth_event(
                action="admin_stats_access",
                email=current_user.get("email", "unknown"),
                success=True,
                ip_address=get_client_ip(request),
                properties={
                    "endpoint": "captcha_stats",
                    "active_captchas": stats["active_captchas"],
                },
            )

        return CaptchaStatsResponse(success=True, stats=stats)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get captcha stats",
            extra={
                "error": str(e),
                "error_type": type(e).__name__,
            },
            exc_info=True,
        )
        return CaptchaStatsResponse(success=False, error="Failed to retrieve stats")


@router.get("/health")
async def captcha_health():
    """Check captcha service health - no logging needed for health checks."""
    return {
        "status": "healthy",
        "active_captchas": len(CAPTCHA_STORE),
        "pending_verifications": len(CAPTCHA_ATTEMPTS),
    }


# Optional: Add rate limiting endpoint
@router.delete("/cleanup")
@log_function("manual_captcha_cleanup")
async def manual_cleanup(
    request: Request,
    current_user: Optional[Dict] = Depends(get_current_user) if HAS_AUTH else None,
):
    """Manually trigger captcha cleanup (admin only)."""
    try:
        if HAS_AUTH and current_user:
            # Admin check here
            pass

        current_time = time.time()
        expired = []

        for captcha_id, data in list(CAPTCHA_STORE.items()):
            if current_time - data["created"] > CAPTCHA_LIFETIME:
                expired.append(captcha_id)

        for captcha_id in expired:
            del CAPTCHA_STORE[captcha_id]
            if captcha_id in CAPTCHA_ATTEMPTS:
                del CAPTCHA_ATTEMPTS[captcha_id]

        if expired:
            logger.info(
                "Manual captcha cleanup performed",
                extra={
                    "cleaned_count": len(expired),
                    "user_id": current_user.get("id") if current_user else "system",
                    "ip": get_client_ip(request),
                },
            )

        return {
            "success": True,
            "cleaned": len(expired),
            "remaining": len(CAPTCHA_STORE),
        }

    except Exception as e:
        logger.error(
            "Failed to perform manual cleanup",
            extra={"error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Cleanup failed")
