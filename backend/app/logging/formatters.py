# app/logging/formatters.py
"""
Custom formatters for structured logging
Provides JSON formatting for production and human-readable formatting for development
"""
import json
import logging
import sys
from datetime import datetime
from typing import Any


class StructuredFormatter(logging.Formatter):
    """
    Formatter that outputs structured JSON logs
    Ideal for production environments and log aggregation systems
    """

    def __init__(self, include_extra: bool = True):
        """
        Initialize the structured formatter

        Args:
            include_extra: Whether to include extra fields from LogRecord
        """
        super().__init__()
        self.include_extra = include_extra

        self.standard_fields = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "exc_info",
            "exc_text",
            "stack_info",
            "getMessage",
            "message",
        }

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON"""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields from record if requested
        if self.include_extra and hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in log_data and not key.startswith("_"):
                    if key not in self.standard_fields:
                        try:
                            json.dumps(value, default=str)
                            log_data[key] = value
                        except (TypeError, ValueError):
                            log_data[key] = str(value)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            log_data["exception_type"] = (
                record.exc_info[0].__name__ if record.exc_info[0] else None
            )

        try:
            return json.dumps(log_data, default=str, separators=(",", ":"))
        except Exception:
            fallback = {
                "timestamp": datetime.now().isoformat(),
                "level": "ERROR",
                "logger": "formatter",
                "message": "Failed to format log",
                "original_message": str(record.getMessage())[:500],
            }
            return json.dumps(fallback)


class DevelopmentFormatter(logging.Formatter):
    """
    Human-readable formatter for development
    Includes color coding and context information
    """

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True, include_context: bool = True):
        """
        Initialize the development formatter

        Args:
            use_colors: Whether to use ANSI color codes
            include_context: Whether to include context information
        """
        self.use_colors = use_colors and self._supports_color()
        self.include_context = include_context

        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        datefmt = "%Y-%m-%d %H:%M:%S"

        super().__init__(fmt=fmt, datefmt=datefmt)

    def _supports_color(self) -> bool:
        """Check if the terminal supports color"""
        if not hasattr(sys.stdout, "isatty"):
            return False
        if not sys.stdout.isatty():
            return False

        if sys.platform == "win32":
            try:
                import colorama

                colorama.init()
                return True
            except ImportError:
                return False

        return True

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record for human readability"""
        base_message = super().format(record)

        # Add color if enabled
        if self.use_colors and record.levelname in self.COLORS:
            level_color = self.COLORS[record.levelname]
            base_message = base_message.replace(
                record.levelname, f"{level_color}{record.levelname}{self.RESET}", 1
            )

        # Add context information if enabled
        if self.include_context:
            context_parts = []

            if hasattr(record, "request_id") and record.request_id:
                context_parts.append(f"req:{record.request_id[:8]}")

            if hasattr(record, "user_id") and record.user_id:
                context_parts.append(f"user:{str(record.user_id)[:8]}")

            if hasattr(record, "campaign_id") and record.campaign_id:
                context_parts.append(f"campaign:{str(record.campaign_id)[:8]}")

            if hasattr(record, "event_type") and record.event_type:
                context_parts.append(f"type:{record.event_type}")

            if hasattr(record, "duration_ms") and record.duration_ms:
                context_parts.append(f"dur:{record.duration_ms:.1f}ms")

            if context_parts:
                context_str = " | ".join(context_parts)
                base_message = f"{base_message} [{context_str}]"

        # Add exception info if present
        if record.exc_info:
            exc_text = self.formatException(record.exc_info)
            if self.use_colors:
                exc_text = f"{self.COLORS['ERROR']}{exc_text}{self.RESET}"
            base_message = f"{base_message}\n{exc_text}"

        return base_message


class CompactFormatter(logging.Formatter):
    """
    Compact formatter for high-volume logging
    Minimal overhead, suitable for performance-critical applications
    """

    def __init__(self):
        """Initialize compact formatter with minimal format"""
        fmt = "%(asctime)s|%(levelname)s|%(name)s|%(message)s"
        datefmt = "%H:%M:%S"
        super().__init__(fmt=fmt, datefmt=datefmt)
