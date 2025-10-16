# app/logging/config.py
"""
Enhanced logging configuration with validation and environment support
Supports loading from environment variables, JSON files, and kwargs
"""
import os
import json
from enum import Enum
from typing import Dict, Any, Optional


class LogLevel(str, Enum):
    """
    Log levels with numeric values for comparison
    """

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"

    @property
    def numeric_value(self) -> int:
        """Get numeric value for level comparison"""
        _levels = {
            "CRITICAL": 50,
            "ERROR": 40,
            "WARNING": 30,
            "INFO": 20,
            "DEBUG": 10,
        }
        return _levels.get(self.value, 20)

    def __le__(self, other) -> bool:
        """Enable level comparison"""
        if isinstance(other, LogLevel):
            return self.numeric_value <= other.numeric_value
        return NotImplemented


class LoggingConfig:
    """
    Enhanced configuration for logging system with validation

    Attributes:
        level: Global log level
        format: Log message format string
        console_enabled: Whether to enable console logging
        console_level: Minimum level for console logs
        database_enabled: Whether to enable database logging
        database_level: Minimum level for database logs
        database_batch_size: Number of logs to batch before flushing
        database_flush_interval: Seconds between automatic flushes
        buffer_enabled: Whether to enable in-memory buffer
        buffer_size: Maximum number of logs to keep in buffer
        buffer_level: Minimum level for buffer logs
        async_logging: Whether to use async logging
        rate_limit_enabled: Whether to enable rate limiting
        rate_limit_burst: Maximum burst size for rate limiting
        rate_limit_rate: Events per second for rate limiting
        development_mode: Whether to use development formatting
        request_logging: Whether to log HTTP requests
    """

    CONFIG_FILE_ENV = "LOG_CONFIG_FILE"

    def __init__(self, **kwargs):
        """Initialize with defaults, then load from environment and kwargs"""
        # Default values
        self.level: LogLevel = LogLevel.INFO
        self.format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

        # Console logging
        self.console_enabled: bool = True
        self.console_level: LogLevel = LogLevel.INFO

        # Database logging
        self.database_enabled: bool = True
        self.database_level: LogLevel = LogLevel.WARNING
        self.database_batch_size: int = 100
        self.database_flush_interval: int = 10

        # Buffer settings
        self.buffer_enabled: bool = True
        self.buffer_size: int = 500
        self.buffer_level: LogLevel = LogLevel.INFO

        # Performance settings
        self.async_logging: bool = True
        self.rate_limit_enabled: bool = True
        self.rate_limit_burst: int = 1000
        self.rate_limit_rate: float = 50.0

        # Development settings
        self.development_mode: bool = False
        self.request_logging: bool = True

        # Load configuration in order of precedence
        self._load_from_defaults()
        self._load_from_config_file()
        self._load_from_env()
        self._load_from_kwargs(kwargs)

        # Validate configuration
        self._validate()

    def _load_from_defaults(self) -> None:
        """Load default configuration based on environment"""
        env = os.getenv("ENVIRONMENT", "production").lower()

        if env in ["development", "dev", "local"]:
            self.development_mode = True
            self.level = LogLevel.DEBUG
            self.console_level = LogLevel.DEBUG
        elif env in ["staging", "test"]:
            self.level = LogLevel.INFO
        elif env in ["production", "prod"]:
            self.level = LogLevel.WARNING
            self.database_level = LogLevel.WARNING

    def _load_from_config_file(self) -> None:
        """Load configuration from JSON file if specified"""
        config_file = os.getenv(self.CONFIG_FILE_ENV)
        if config_file and os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config_data = json.load(f)
                    for key, value in config_data.items():
                        if hasattr(self, key):
                            setattr(self, key, self._convert_value(key, value))
            except Exception as e:
                print(f"Warning: Failed to load config file {config_file}: {e}")

    def _load_from_env(self) -> None:
        """Load configuration from environment variables with LOG_ prefix"""
        env_mappings = {
            "LOG_LEVEL": ("level", lambda x: LogLevel(x.upper())),
            "LOG_FORMAT": ("format", str),
            "LOG_CONSOLE_ENABLED": (
                "console_enabled",
                lambda x: x.lower() in ("true", "1", "yes", "on"),
            ),
            "LOG_CONSOLE_LEVEL": ("console_level", lambda x: LogLevel(x.upper())),
            "LOG_DATABASE_ENABLED": (
                "database_enabled",
                lambda x: x.lower() in ("true", "1", "yes", "on"),
            ),
            "LOG_DATABASE_LEVEL": ("database_level", lambda x: LogLevel(x.upper())),
            "LOG_DATABASE_BATCH_SIZE": ("database_batch_size", int),
            "LOG_DATABASE_FLUSH_INTERVAL": ("database_flush_interval", int),
            "LOG_BUFFER_ENABLED": (
                "buffer_enabled",
                lambda x: x.lower() in ("true", "1", "yes", "on"),
            ),
            "LOG_BUFFER_SIZE": ("buffer_size", int),
            "LOG_BUFFER_LEVEL": ("buffer_level", lambda x: LogLevel(x.upper())),
            "LOG_ASYNC_LOGGING": (
                "async_logging",
                lambda x: x.lower() in ("true", "1", "yes", "on"),
            ),
            "LOG_RATE_LIMIT_ENABLED": (
                "rate_limit_enabled",
                lambda x: x.lower() in ("true", "1", "yes", "on"),
            ),
            "LOG_RATE_LIMIT_BURST": ("rate_limit_burst", int),
            "LOG_RATE_LIMIT_RATE": ("rate_limit_rate", float),
            "LOG_DEVELOPMENT_MODE": (
                "development_mode",
                lambda x: x.lower() in ("true", "1", "yes", "on"),
            ),
            "LOG_REQUEST_LOGGING": (
                "request_logging",
                lambda x: x.lower() in ("true", "1", "yes", "on"),
            ),
        }

        for env_key, (attr_name, converter) in env_mappings.items():
            if env_key in os.environ:
                try:
                    value = converter(os.environ[env_key])
                    setattr(self, attr_name, value)
                except (ValueError, TypeError):
                    print(
                        f"Warning: Invalid value for {env_key}: {os.environ[env_key]}"
                    )

    def _load_from_kwargs(self, kwargs: Dict[str, Any]) -> None:
        """Load configuration from provided keyword arguments"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, self._convert_value(key, value))

    def _convert_value(self, key: str, value: Any) -> Any:
        """Convert string values to appropriate types"""
        if key.endswith("_enabled") or key in [
            "development_mode",
            "request_logging",
            "async_logging",
            "rate_limit_enabled",
        ]:
            if isinstance(value, str):
                return str(value).lower() in ("true", "1", "yes", "on")
            return bool(value)

        elif key in [
            "database_batch_size",
            "database_flush_interval",
            "buffer_size",
            "rate_limit_burst",
        ]:
            return int(value) if isinstance(value, str) else value

        elif key in ["rate_limit_rate"]:
            return float(value) if isinstance(value, str) else value

        elif key in [
            "level",
            "console_level",
            "database_level",
            "buffer_level",
        ]:
            if isinstance(value, str):
                return LogLevel(value.upper())
            return value

        return value

    def _validate(self) -> None:
        """Validate configuration values"""
        if self.rate_limit_enabled:
            if self.rate_limit_burst < 1:
                self.rate_limit_burst = 1000
            if self.rate_limit_rate <= 0:
                self.rate_limit_rate = 50.0

        if self.database_batch_size < 1:
            self.database_batch_size = 100

        if self.buffer_size < 1:
            self.buffer_size = 500

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for serialization"""
        return {
            key: value.value if isinstance(value, LogLevel) else value
            for key, value in self.__dict__.items()
            if not key.startswith("_")
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert config to JSON string"""
        return json.dumps(self.to_dict(), indent=indent)

    def save_to_file(self, filepath: str) -> None:
        """Save configuration to JSON file"""
        try:
            with open(filepath, "w") as f:
                f.write(self.to_json())
        except Exception as e:
            print(f"Failed to save configuration: {e}")

    def __repr__(self) -> str:
        items = [f"{k}={v}" for k, v in self.to_dict().items()]
        display_items = items[:5] if len(items) > 5 else items
        suffix = "..." if len(items) > 5 else ""
        return f"LoggingConfig({', '.join(display_items)}{suffix})"