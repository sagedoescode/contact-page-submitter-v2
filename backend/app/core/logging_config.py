# app/core/logging_config.py
"""
Centralized logging configuration for the application.
Properly suppresses verbose SQLAlchemy and other library logs.
"""

import logging
import logging.config
import sys
from typing import Dict, Any
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_file: str = None) -> None:
    """
    Configure logging for the entire application.
    
    Args:
        log_level: The logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
    """
    
    # Create logs directory if needed
    if log_file:
        log_dir = Path(log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    
    # Define logging configuration
    config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            },
            "simple": {
                "format": "%(levelname)s: %(message)s"
            },
            "detailed": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "default",
                "stream": "ext://sys.stdout"
            }
        },
        "root": {
            "level": log_level,
            "handlers": ["console"]
        },
        "loggers": {
            # SQLAlchemy loggers - set to WARNING to reduce verbosity
            "sqlalchemy": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "sqlalchemy.engine": {
                "level": "WARNING",  # Only show warnings and errors
                "handlers": ["console"],
                "propagate": False
            },
            "sqlalchemy.engine.Engine": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "sqlalchemy.pool": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "sqlalchemy.dialects": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "sqlalchemy.orm": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            
            # Alembic migrations
            "alembic": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "alembic.runtime.migration": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            
            # FastAPI/Uvicorn
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "uvicorn.error": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "uvicorn.access": {
                "level": "WARNING",  # Reduce access log verbosity
                "handlers": ["console"],
                "propagate": False
            },
            "fastapi": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            
            # HTTP libraries
            "httpx": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "httpcore": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "urllib3": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "aiohttp": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            
            # Other noisy libraries
            "asyncio": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "watchfiles": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "multipart": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            "passlib": {
                "level": "WARNING",
                "handlers": ["console"],
                "propagate": False
            },
            
            # Your application loggers - keep at INFO level
            "app": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "app.main": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "app.routers": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "app.core": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "app.api": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            },
            "app.services": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False
            }
        }
    }
    
    # Add file handler if log_file is specified
    if log_file:
        config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level,
            "formatter": "detailed",
            "filename": log_file,
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf8"
        }
        # Add file handler to root and app loggers
        config["root"]["handlers"].append("file")
        for logger_name in config["loggers"]:
            if logger_name.startswith("app"):
                config["loggers"][logger_name]["handlers"].append("file")
    
    # Apply configuration
    logging.config.dictConfig(config)
    
    # Additional runtime suppression for SQLAlchemy
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
    
    # Log the configuration
    logger = logging.getLogger("app.core.logging_config")
    logger.info(f"Logging configured with level: {log_level}")
    if log_file:
        logger.info(f"Logging to file: {log_file}")


def suppress_sqlalchemy_logs():
    """
    Specifically suppress SQLAlchemy logs.
    Call this after database initialization if needed.
    """
    sqlalchemy_loggers = [
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
        "sqlalchemy.pool",
        "sqlalchemy.dialects",
        "sqlalchemy.orm",
        "sqlalchemy.engine.base.Engine"
    ]
    
    for logger_name in sqlalchemy_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.WARNING)
        logger.propagate = False


def set_library_log_levels(level: str = "WARNING"):
    """
    Set log levels for third-party libraries.
    
    Args:
        level: The logging level for libraries
    """
    libraries = [
        "sqlalchemy",
        "uvicorn.access",
        "httpx",
        "httpcore",
        "urllib3",
        "asyncio",
        "watchfiles",
        "multipart",
        "aiohttp"
    ]
    
    log_level = getattr(logging, level.upper(), logging.WARNING)
    
    for lib in libraries:
        logging.getLogger(lib).setLevel(log_level)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.
    
    Args:
        name: The logger name (usually __name__)
    
    Returns:
        A configured logger instance
    """
    return logging.getLogger(name)


# Initialize logging on import
setup_logging()
suppress_sqlalchemy_logs()