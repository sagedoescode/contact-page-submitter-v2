# app/core/dependencies.py - Optimized authentication with security logging
"""Authentication and authorization dependencies with comprehensive security audit trail"""

from typing import Optional, List
from datetime import datetime

from fastapi import Depends, HTTPException, status, Query, Header, Request
from sqlalchemy.orm import Session

# Import database and models
from app.core.database import get_db
from app.models.user import User

# Import from centralized security module
from app.core.security import verify_token, JWT_SECRET, JWT_ALGORITHM

# Import logging
from app.logging import get_logger

logger = get_logger(__name__)

# Track authentication failures to detect brute force
_auth_failures = {}  # IP -> (count, last_attempt_time)
_AUTH_FAILURE_THRESHOLD = 10  # Log warning after this many failures
_AUTH_FAILURE_WINDOW = 300  # 5 minutes


def _get_client_ip(request: Request = None) -> str:
    """Extract client IP from request."""
    if not request:
        return "unknown"

    # Check X-Forwarded-For header first (for proxies/load balancers)
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    # Fall back to direct client
    if request.client:
        return request.client.host

    return "unknown"


def _track_auth_failure(ip: str, reason: str):
    """Track authentication failures per IP to detect brute force attacks."""
    current_time = datetime.utcnow().timestamp()

    if ip not in _auth_failures:
        _auth_failures[ip] = {"count": 1, "last_attempt": current_time}
    else:
        last_attempt = _auth_failures[ip]["last_attempt"]
        time_diff = current_time - last_attempt

        # Reset count if outside the window
        if time_diff > _AUTH_FAILURE_WINDOW:
            _auth_failures[ip] = {"count": 1, "last_attempt": current_time}
        else:
            _auth_failures[ip]["count"] += 1
            _auth_failures[ip]["last_attempt"] = current_time

            # Log warning if threshold exceeded
            if _auth_failures[ip]["count"] >= _AUTH_FAILURE_THRESHOLD:
                logger.security_event(
                    event="auth_brute_force_detected",
                    severity="error",
                    properties={
                        "ip": ip,
                        "failure_count": _auth_failures[ip]["count"],
                        "reason": reason,
                        "window_seconds": _AUTH_FAILURE_WINDOW,
                    },
                )


def get_current_user(
    authorization: Optional[str] = Header(None),
    request: Request = None,
    db: Session = Depends(get_db),
) -> User:
    """Get current user from JWT token with comprehensive security logging."""

    client_ip = _get_client_ip(request)

    if not authorization:
        _track_auth_failure(client_ip, "missing_token")

        # Only log if this might be a brute force attempt
        if client_ip in _auth_failures and _auth_failures[client_ip]["count"] >= 5:
            logger.security_event(
                event="auth_missing_token_repeated",
                severity="warning",
                properties={
                    "ip": client_ip,
                    "failure_count": _auth_failures[client_ip]["count"],
                },
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Parse Bearer token
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            _track_auth_failure(client_ip, "invalid_scheme")

            logger.security_event(
                event="auth_invalid_scheme",
                severity="warning",
                properties={
                    "ip": client_ip,
                    "scheme": parts[0] if parts else "none",
                },
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication scheme",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = parts[1]

        # Verify token using centralized function
        payload = verify_token(token)
        if not payload:
            _track_auth_failure(client_ip, "invalid_token")

            logger.security_event(
                event="auth_invalid_token",
                severity="warning",
                properties={
                    "ip": client_ip,
                    "token_prefix": token[:10]
                    + "...",  # Log first 10 chars for debugging
                },
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get email from token
        email = payload.get("sub")
        if not email:
            _track_auth_failure(client_ip, "missing_email")

            logger.security_event(
                event="auth_invalid_payload",
                severity="warning",
                properties={
                    "ip": client_ip,
                    "reason": "missing_email",
                },
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get user from database
        user = db.query(User).filter(User.email == email).first()
        if not user:
            _track_auth_failure(client_ip, "user_not_found")

            logger.security_event(
                event="auth_user_not_found",
                severity="warning",
                properties={
                    "ip": client_ip,
                    "email": email,  # Log email since user doesn't exist
                },
            )

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # Check if user is active
        if not user.is_active:
            logger.security_event(
                event="auth_inactive_user_attempt",
                severity="warning",
                properties={
                    "ip": client_ip,
                    "user_id": str(user.id),
                    "email": user.email,
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive"
            )

        # Success - clear any tracked failures for this IP
        if client_ip in _auth_failures:
            del _auth_failures[client_ip]

        return user

    except HTTPException:
        raise
    except Exception as e:
        _track_auth_failure(client_ip, "exception")

        logger.error(
            "Authentication exception",
            extra={
                "event": "auth_exception",
                "ip": client_ip,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Return user if token is present/valid; else None. No logging for optional auth."""
    if not authorization:
        return None

    try:
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        token = parts[1]
        payload = verify_token(token)
        if not payload:
            return None

        email = payload.get("sub")
        if not email:
            return None

        return db.query(User).filter(User.email == email).first()
    except Exception:
        return None


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Ensure user is active. No additional logging needed."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_admin_user(
    current_user: User = Depends(get_current_user),
    request: Request = None,
) -> User:
    """Check if user is admin or owner with security logging."""
    role = (getattr(current_user, "role", "") or "").lower()

    if role in {"admin", "owner"} or getattr(current_user, "is_superuser", False):
        return current_user

    # Log unauthorized admin access attempt
    logger.security_event(
        event="auth_unauthorized_admin_access",
        severity="warning",
        properties={
            "user_id": str(current_user.id),
            "email": current_user.email,
            "role": role,
            "ip": _get_client_ip(request),
        },
    )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required",
    )


def get_admin_or_owner(
    current_user: User = Depends(get_current_user),
    request: Request = None,
) -> User:
    """Require admin or owner role with security logging."""
    role = (getattr(current_user, "role", "") or "").lower()

    if role not in {"admin", "owner"}:
        logger.security_event(
            event="auth_unauthorized_admin_owner_access",
            severity="warning",
            properties={
                "user_id": str(current_user.id),
                "email": current_user.email,
                "role": role,
                "ip": _get_client_ip(request),
            },
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Owner access required",
        )

    return current_user


def get_owner_only(
    current_user: User = Depends(get_current_user),
    request: Request = None,
) -> User:
    """Require owner role only with security logging."""
    role = (getattr(current_user, "role", "") or "").lower()

    if role != "owner":
        logger.security_event(
            event="auth_unauthorized_owner_access",
            severity="warning",
            properties={
                "user_id": str(current_user.id),
                "email": current_user.email,
                "role": role,
                "ip": _get_client_ip(request),
            },
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required"
        )

    return current_user


def get_moderator_or_above(
    current_user: User = Depends(get_current_user),
    request: Request = None,
) -> User:
    """Require moderator, admin, or owner role with security logging."""
    role = (getattr(current_user, "role", "") or "").lower()

    if role not in {"moderator", "admin", "owner"}:
        logger.security_event(
            event="auth_unauthorized_moderator_access",
            severity="warning",
            properties={
                "user_id": str(current_user.id),
                "email": current_user.email,
                "role": role,
                "ip": _get_client_ip(request),
            },
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Moderator access or above required",
        )

    return current_user


def require_role(required_roles: List[str]):
    """Decorator to require specific roles with security logging."""

    def role_checker(
        current_user: User = Depends(get_current_user),
        request: Request = None,
    ) -> User:
        user_role = (getattr(current_user, "role", "") or "").lower()

        if user_role not in [r.lower() for r in required_roles]:
            logger.security_event(
                event="auth_unauthorized_role_access",
                severity="warning",
                properties={
                    "user_id": str(current_user.id),
                    "email": current_user.email,
                    "user_role": user_role,
                    "required_roles": required_roles,
                    "ip": _get_client_ip(request),
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of these roles: {', '.join(required_roles)}",
            )

        return current_user

    return role_checker


def has_permission(user: User, permission: str) -> bool:
    """Check if user has specific permission. No logging for permission checks."""
    role = (getattr(user, "role", "") or "").lower()

    # Admin and owner have all permissions
    if role in {"admin", "owner"}:
        return True

    # Permission mappings
    permission_map = {
        "view_users": ["admin", "owner", "moderator"],
        "edit_users": ["admin", "owner"],
        "delete_users": ["owner"],
        "view_campaigns": ["admin", "owner", "user"],
        "edit_campaigns": ["admin", "owner", "user"],
        "delete_campaigns": ["admin", "owner"],
        "view_analytics": ["admin", "owner", "user"],
        "view_own_analytics": ["admin", "owner", "user"],
        "view_logs": ["admin", "owner"],
        "manage_system": ["owner"],
    }

    allowed_roles = permission_map.get(permission, [])
    return role in allowed_roles


def require_permission(permission: str):
    """Decorator to require specific permission with security logging."""

    def permission_checker(
        current_user: User = Depends(get_current_user),
        request: Request = None,
    ) -> User:
        if not has_permission(current_user, permission):
            logger.security_event(
                event="auth_unauthorized_permission",
                severity="warning",
                properties={
                    "user_id": str(current_user.id),
                    "email": current_user.email,
                    "role": getattr(current_user, "role", ""),
                    "permission": permission,
                    "ip": _get_client_ip(request),
                },
            )

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}",
            )

        return current_user

    return permission_checker


# WebSocket authentication
async def get_current_user_ws(
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """WebSocket authentication using query parameter. No logging for optional."""
    if not token:
        return None

    try:
        payload = verify_token(token)
        if not payload:
            return None

        email = payload.get("sub")
        if not email:
            return None

        return db.query(User).filter(User.email == email).first()
    except Exception:
        return None


async def get_current_user_ws_required(
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> User:
    """WebSocket authentication that requires valid user with security logging."""
    user = await get_current_user_ws(token, db)

    if not user:
        logger.security_event(
            event="ws_auth_failed",
            severity="warning",
            properties={
                "reason": "invalid_or_missing_token",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WebSocket authentication failed",
        )

    return user


def get_user_from_token(token: str, db: Session) -> Optional[User]:
    """Get user from JWT token. No logging - utility function."""
    payload = verify_token(token)
    if not payload:
        return None

    email = payload.get("sub")
    if not email:
        return None

    return db.query(User).filter(User.email == email).first()


def debug_token_info(authorization: Optional[str] = Header(None)) -> dict:
    """Debug token information. Only for debugging, not production."""
    import jwt

    if not authorization:
        return {"error": "No token provided"}

    try:
        parts = authorization.split()
        if len(parts) != 2:
            return {"error": f"Invalid format. Parts: {len(parts)}"}

        token = parts[1]

        # Decode without verification
        unverified = jwt.decode(token, options={"verify_signature": False})

        # Try with verification
        try:
            verified = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            return {
                "status": "valid",
                "payload": verified,
                "expires_at": (
                    datetime.fromtimestamp(verified.get("exp", 0)).isoformat()
                    if verified.get("exp")
                    else None
                ),
            }
        except jwt.ExpiredSignatureError:
            return {
                "status": "expired",
                "unverified_payload": unverified,
                "error": "Token has expired",
            }
        except jwt.InvalidTokenError as e:
            return {
                "status": "invalid",
                "unverified_payload": unverified,
                "error": str(e),
            }

    except Exception as e:
        return {"error": f"Failed to decode token: {str(e)}"}


def get_auth_stats() -> dict:
    """Get authentication statistics for monitoring."""
    current_time = datetime.utcnow().timestamp()

    # Clean old entries
    expired_ips = [
        ip
        for ip, data in _auth_failures.items()
        if current_time - data["last_attempt"] > _AUTH_FAILURE_WINDOW
    ]
    for ip in expired_ips:
        del _auth_failures[ip]

    # Calculate stats
    total_failing_ips = len(_auth_failures)
    high_failure_ips = sum(1 for data in _auth_failures.values() if data["count"] >= 5)

    return {
        "active_failure_tracking": total_failing_ips,
        "high_failure_ips": high_failure_ips,
        "threshold": _AUTH_FAILURE_THRESHOLD,
        "window_seconds": _AUTH_FAILURE_WINDOW,
    }


# Export all
__all__ = [
    "get_current_user",
    "get_current_user_optional",
    "get_current_active_user",
    "get_admin_user",
    "get_admin_or_owner",
    "get_owner_only",
    "get_moderator_or_above",
    "require_role",
    "require_permission",
    "has_permission",
    "get_user_from_token",
    "get_current_user_ws",
    "get_current_user_ws_required",
    "debug_token_info",
    "get_auth_stats",
]
