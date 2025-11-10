# app/core/config.py - Optimized configuration with smart logging
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional, Dict, Any, List, Literal, Union
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Track if we've already logged configuration (only log once on startup)
_config_logged = False


@dataclass
class BrowserSettings:
    """Browser configuration settings - single source of truth"""

    @property
    def headless(self) -> bool:
        """Determine if browser should run headless based on environment"""
        # DEV_AUTOMATION_HEADFUL takes precedence
        if os.getenv("DEV_AUTOMATION_HEADFUL"):
            return not (os.getenv("DEV_AUTOMATION_HEADFUL", "false").lower() == "true")
        # Fallback to BROWSER_HEADLESS
        return os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

    @property
    def slow_mo(self) -> int:
        """Get slow motion delay in milliseconds"""
        # Try DEV_AUTOMATION_SLOWMO_MS first, then BROWSER_SLOW_MO_MS
        return int(
            os.getenv("DEV_AUTOMATION_SLOWMO_MS", os.getenv("BROWSER_SLOW_MO_MS", "0"))
        )

    viewport_width: int = 1920
    viewport_height: int = 1080
    page_load_timeout: int = 30000

    @property
    def is_visible(self) -> bool:
        """Helper to check if browser will be visible"""
        return not self.headless

    def log_settings(self) -> dict:
        """Return current settings for logging"""
        return {
            "headless": self.headless,
            "visible": self.is_visible,
            "slow_mo_ms": self.slow_mo,
            "viewport": f"{self.viewport_width}x{self.viewport_height}",
            "timeout_ms": self.page_load_timeout,
        }

    def validate(self) -> List[str]:
        """Validate browser settings and return warnings"""
        warnings = []

        if self.slow_mo > 1000:
            warnings.append(
                f"Very high slow_mo setting: {self.slow_mo}ms may impact performance"
            )

        if self.page_load_timeout < 5000:
            warnings.append(
                f"Low page_load_timeout: {self.page_load_timeout}ms may cause failures"
            )

        return warnings


@dataclass
class Settings:
    """Application settings using dataclass for simplicity"""

    # Application
    APP_NAME: str = field(
        default_factory=lambda: os.getenv("APP_NAME", "Contact Page Submitter")
    )
    VERSION: str = field(default_factory=lambda: os.getenv("APP_VERSION", "2.0.0"))
    DEBUG: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "False").lower() == "true"
    )
    PORT: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))

    # Database
    DATABASE_URL: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql://user:password@localhost/cps_db"
        )
    )

    # Security
    SECRET_KEY: str = field(
        default_factory=lambda: os.getenv(
            "SECRET_KEY", "your-secret-key-change-in-production"
        )
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = field(
        default_factory=lambda: int(os.getenv("JWT_EXPIRATION_HOURS", "24")) * 60
    )

    # CORS
    CORS_ORIGINS: List[str] = field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:3000",
        ]
    )

    # Browser settings - using property-based class
    browser: BrowserSettings = field(default_factory=BrowserSettings)

    # Email settings
    SMTP_HOST: Optional[str] = field(default_factory=lambda: os.getenv("SMTP_HOST"))
    SMTP_PORT: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    SMTP_USER: Optional[str] = field(default_factory=lambda: os.getenv("SMTP_USER"))
    SMTP_PASSWORD: Optional[str] = field(
        default_factory=lambda: os.getenv("SMTP_PASSWORD")
    )
    FROM_EMAIL: Optional[str] = field(default_factory=lambda: os.getenv("FROM_EMAIL"))

    # Captcha settings
    CAPTCHA_ENCRYPTION_KEY: str = field(
        default_factory=lambda: os.getenv(
            "CAPTCHA_ENCRYPTION_KEY", "ackvtc-ge9RXynxBAjoiuiyi8QpzcSCd5jHqZJY7IiI="
        )
    )
    CAPTCHA_DBC_API_URL: str = field(
        default_factory=lambda: os.getenv(
            "CAPTCHA_DBC_API_URL", "http://api.dbcapi.me/api"
        )
    )
    CAPTCHA_SOLVE_TIMEOUT: int = field(
        default_factory=lambda: int(os.getenv("CAPTCHA_SOLVE_TIMEOUT", "120"))
    )

    # Worker settings
    WORKER_CONCURRENCY: int = field(
        default_factory=lambda: int(os.getenv("MAX_CONCURRENT_SUBMISSIONS", "5"))
    )
    SUBMISSION_DELAY: float = field(
        default_factory=lambda: float(os.getenv("SUBMISSION_DELAY_SECONDS", "3.0"))
    )

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    )

    # Logging
    LOG_LEVEL: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    LOG_FILE: Optional[str] = field(default_factory=lambda: os.getenv("LOG_FILE"))

    # Form processing
    FORM_TIMEOUT_SECONDS: int = field(
        default_factory=lambda: int(os.getenv("FORM_TIMEOUT_SECONDS", "30"))
    )
    EMAIL_EXTRACTION_TIMEOUT: int = field(
        default_factory=lambda: int(os.getenv("EMAIL_EXTRACTION_TIMEOUT", "15"))
    )

    # Feature flags
    FEATURE_USE_BROWSER: bool = field(
        default_factory=lambda: os.getenv("FEATURE_USE_BROWSER", "true").lower()
        == "true"
    )
    FEATURE_CAPTCHA_SOLVING: bool = field(
        default_factory=lambda: os.getenv("FEATURE_CAPTCHA_SOLVING", "true").lower()
        == "true"
    )
    FEATURE_EMAIL_FALLBACK: bool = field(
        default_factory=lambda: os.getenv("FEATURE_EMAIL_FALLBACK", "true").lower()
        == "true"
    )

    def validate(self) -> Dict[str, List[str]]:
        """Validate all settings and return errors/warnings"""
        errors = []
        warnings = []

        # Security validation
        if self.SECRET_KEY == "your-secret-key-change-in-production":
            errors.append("Using default SECRET_KEY - MUST be changed in production")

        if len(self.SECRET_KEY) < 32:
            warnings.append(
                f"SECRET_KEY is short ({len(self.SECRET_KEY)} chars) - recommend 32+ chars"
            )

        # Database validation
        if "localhost" in self.DATABASE_URL and not self.DEBUG:
            warnings.append("Using localhost database in non-DEBUG mode")

        # Email validation
        if self.SMTP_HOST and not self.SMTP_USER:
            warnings.append("SMTP_HOST set but SMTP_USER missing")

        if self.SMTP_USER and not self.SMTP_PASSWORD:
            errors.append("SMTP_USER set but SMTP_PASSWORD missing")

        # Worker validation
        if self.WORKER_CONCURRENCY > 20:
            warnings.append(
                f"High concurrency ({self.WORKER_CONCURRENCY}) may impact performance"
            )

        if self.WORKER_CONCURRENCY < 1:
            errors.append(
                f"Invalid WORKER_CONCURRENCY: {self.WORKER_CONCURRENCY} (must be >= 1)"
            )

        # Rate limiting validation
        if self.RATE_LIMIT_PER_MINUTE < 10:
            warnings.append(
                f"Very low rate limit: {self.RATE_LIMIT_PER_MINUTE}/min may impact usability"
            )

        # Timeout validation
        if self.FORM_TIMEOUT_SECONDS < 10:
            warnings.append(
                f"Low FORM_TIMEOUT ({self.FORM_TIMEOUT_SECONDS}s) may cause failures"
            )

        if self.CAPTCHA_SOLVE_TIMEOUT < 30:
            warnings.append(
                f"Low CAPTCHA_SOLVE_TIMEOUT ({self.CAPTCHA_SOLVE_TIMEOUT}s) may fail for complex captchas"
            )

        # Feature flag validation
        if not self.FEATURE_USE_BROWSER and not self.FEATURE_EMAIL_FALLBACK:
            errors.append(
                "Both browser and email fallback disabled - no submission method available"
            )

        # Browser validation
        browser_warnings = self.browser.validate()
        warnings.extend(browser_warnings)

        return {
            "errors": errors,
            "warnings": warnings,
        }

    def get_safe_config(self) -> Dict[str, Any]:
        """Get configuration with sensitive values masked"""
        return {
            "app_name": self.APP_NAME,
            "version": self.VERSION,
            "debug": self.DEBUG,
            "port": self.PORT,
            "database_url": self._mask_connection_string(self.DATABASE_URL),
            "secret_key": self._mask_secret(self.SECRET_KEY),
            "jwt_expiration_minutes": self.ACCESS_TOKEN_EXPIRE_MINUTES,
            "cors_origins": self.CORS_ORIGINS,
            "browser": self.browser.log_settings(),
            "smtp_configured": bool(self.SMTP_HOST and self.SMTP_USER),
            "smtp_host": self.SMTP_HOST,
            "captcha_api_url": self.CAPTCHA_DBC_API_URL,
            "captcha_timeout": self.CAPTCHA_SOLVE_TIMEOUT,
            "worker_concurrency": self.WORKER_CONCURRENCY,
            "submission_delay": self.SUBMISSION_DELAY,
            "rate_limit_enabled": self.RATE_LIMIT_ENABLED,
            "rate_limit_per_minute": self.RATE_LIMIT_PER_MINUTE,
            "log_level": self.LOG_LEVEL,
            "form_timeout": self.FORM_TIMEOUT_SECONDS,
            "email_timeout": self.EMAIL_EXTRACTION_TIMEOUT,
            "features": {
                "browser": self.FEATURE_USE_BROWSER,
                "captcha_solving": self.FEATURE_CAPTCHA_SOLVING,
                "email_fallback": self.FEATURE_EMAIL_FALLBACK,
            },
        }

    @staticmethod
    def _mask_connection_string(url: str) -> str:
        """Mask password in database URL"""
        if "://" not in url:
            return url

        try:
            # Format: postgresql://user:password@host/db
            parts = url.split("://")
            if len(parts) != 2:
                return url

            protocol = parts[0]
            rest = parts[1]

            if "@" not in rest:
                return url

            user_pass, host_db = rest.split("@", 1)

            if ":" in user_pass:
                user, _ = user_pass.split(":", 1)
                return f"{protocol}://{user}:***@{host_db}"

            return url
        except:
            return "***"

    @staticmethod
    def _mask_secret(secret: str) -> str:
        """Mask secret key showing only first and last 4 chars"""
        if len(secret) <= 8:
            return "***"
        return f"{secret[:4]}...{secret[-4:]}"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance - logs only once on first call"""
    global _config_logged

    settings = Settings()

    # Only log configuration once on startup
    if not _config_logged:
        from app.logging import get_logger

        logger = get_logger(__name__)

        # Validate settings
        validation = settings.validate()

        # Log errors (blocking issues)
        if validation["errors"]:
            logger.error(
                "Configuration errors detected",
                extra={
                    "event": "config_validation_failed",
                    "errors": validation["errors"],
                },
            )
            # In production, you might want to raise an exception here
            # raise RuntimeError("Configuration validation failed")

        # Log warnings (non-blocking issues)
        if validation["warnings"]:
            logger.warning(
                "Configuration warnings detected",
                extra={
                    "event": "config_validation_warnings",
                    "warnings": validation["warnings"],
                },
            )

        # Log successful configuration (only if no errors)
        if not validation["errors"]:
            logger.info(
                "Application configuration loaded",
                extra={
                    "event": "config_loaded",
                    "config": settings.get_safe_config(),
                    "has_warnings": len(validation["warnings"]) > 0,
                },
            )

        _config_logged = True

    return settings


def reload_settings() -> Settings:
    """Force reload settings (clears cache) - use with caution"""
    global _config_logged

    from app.logging import get_logger

    logger = get_logger(__name__)

    # Clear the cache
    get_settings.cache_clear()
    _config_logged = False

    logger.warning(
        "Configuration reloaded",
        extra={
            "event": "config_reloaded",
            "warning": "Settings cache cleared - new configuration loaded",
        },
    )

    return get_settings()


def get_config_for_endpoint() -> Dict[str, Any]:
    """Get safe configuration for admin/debug endpoints"""
    settings = get_settings()
    config = settings.get_safe_config()
    validation = settings.validate()

    return {
        **config,
        "validation": {
            "has_errors": len(validation["errors"]) > 0,
            "has_warnings": len(validation["warnings"]) > 0,
            "error_count": len(validation["errors"]),
            "warning_count": len(validation["warnings"]),
        },
    }
