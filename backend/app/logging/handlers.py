# app/logging/handlers.py
"""
Custom logging handlers for different backends
Provides database, buffer, and file handlers with batching and async support
"""
import asyncio
import queue
import threading
import time
import json
from collections import deque
from typing import Dict, Any, List, Optional, Deque, Union
import logging
from logging.handlers import QueueHandler, QueueListener
from datetime import datetime, timedelta

# Import database utilities with fallback
try:
    from app.core.database import SessionLocal
    from app.utils.logs import insert_app_log
except ImportError:
    # Fallback if database modules not available
    SessionLocal = None

    def insert_app_log(*args, **kwargs):
        pass


class BufferHandler(logging.Handler):
    """
    In-memory ring buffer for recent logs
    Provides fast access to recent log entries without database overhead
    """

    def __init__(
        self,
        buffer_size: int = 1000,
        level: int = logging.NOTSET,
        overflow_strategy: str = "drop_oldest",
    ):
        """
        Initialize the buffer handler

        Args:
            buffer_size: Maximum number of log entries to keep
            level: Minimum log level to handle
            overflow_strategy: What to do when buffer is full
                              ("drop_oldest", "drop_newest", "drop_current")
        """
        super().__init__(level)
        self.buffer_size = buffer_size
        self.overflow_strategy = overflow_strategy
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=buffer_size)
        self._lock = threading.RLock()

        # Statistics
        self._total_logs = 0
        self._dropped_logs = 0
        self._last_clear = time.time()

    def emit(self, record: logging.LogRecord) -> None:
        """
        Handle a log record

        Args:
            record: LogRecord to process
        """
        try:
            # Convert record to dict
            log_data = self._format_record(record)

            with self._lock:
                self._total_logs += 1

                if (
                    self.overflow_strategy == "drop_current"
                    and len(self._buffer) >= self.buffer_size
                ):
                    self._dropped_logs += 1
                    return

                self._buffer.append(log_data)

                # Track drops for drop_oldest (automatic with deque maxlen)
                if (
                    len(self._buffer) == self.buffer_size
                    and self._total_logs > self.buffer_size
                ):
                    self._dropped_logs += 1

        except Exception:
            self.handleError(record)

    def _format_record(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Convert LogRecord to dictionary"""
        log_data = {
            "timestamp": time.time(),
            "iso_timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "level_no": record.levelno,
            "logger": record.name,
            "message": self.format(record),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.thread,
            "thread_name": record.threadName,
        }

        # Add extra fields
        for key, value in record.__dict__.items():
            if not key.startswith("_") and key not in log_data:
                # Skip standard fields
                if key not in [
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
                ]:
                    try:
                        # Ensure value is serializable
                        json.dumps(value, default=str)
                        log_data[key] = value
                    except (TypeError, ValueError):
                        log_data[key] = str(value)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.format(record)

        return log_data

    def get_recent(
        self,
        limit: Optional[int] = None,
        level: Optional[str] = None,
        since: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get recent log entries

        Args:
            limit: Maximum number of logs to return
            level: Filter by log level (e.g., "ERROR", "WARNING")
            since: Only return logs since this timestamp

        Returns:
            List of log dictionaries
        """
        with self._lock:
            logs = list(self._buffer)

            # Apply filters
            if level:
                logs = [log for log in logs if log.get("level") == level.upper()]

            if since:
                logs = [log for log in logs if log.get("timestamp", 0) >= since]

            if limit and limit < len(logs):
                logs = logs[-limit:]

            return logs

    def get_campaign_logs(
        self, campaign_id: str, limit: Optional[int] = None, level: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get logs for a specific campaign

        Args:
            campaign_id: Campaign identifier
            limit: Maximum number of logs to return
            level: Filter by log level

        Returns:
            List of log dictionaries for the campaign
        """
        with self._lock:
            campaign_logs = [
                log for log in self._buffer if log.get("campaign_id") == campaign_id
            ]

            if level:
                campaign_logs = [
                    log for log in campaign_logs if log.get("level") == level.upper()
                ]

            if limit and limit < len(campaign_logs):
                campaign_logs = campaign_logs[-limit:]

            return campaign_logs

    def get_user_logs(
        self, user_id: str, limit: Optional[int] = None, level: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get logs for a specific user

        Args:
            user_id: User identifier
            limit: Maximum number of logs to return
            level: Filter by log level

        Returns:
            List of log dictionaries for the user
        """
        with self._lock:
            user_logs = [log for log in self._buffer if log.get("user_id") == user_id]

            if level:
                user_logs = [
                    log for log in user_logs if log.get("level") == level.upper()
                ]

            if limit and limit < len(user_logs):
                user_logs = user_logs[-limit:]

            return user_logs

    def search(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search logs by message content

        Args:
            query: Search query (case-insensitive)
            limit: Maximum number of results

        Returns:
            List of matching log dictionaries
        """
        query_lower = query.lower()

        with self._lock:
            matching_logs = [
                log
                for log in self._buffer
                if query_lower in log.get("message", "").lower()
            ]

            if limit and limit < len(matching_logs):
                matching_logs = matching_logs[-limit:]

            return matching_logs

    def clear(self) -> None:
        """Clear the buffer"""
        with self._lock:
            self._buffer.clear()
            self._last_clear = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get buffer statistics

        Returns:
            Dictionary containing buffer stats
        """
        with self._lock:
            level_counts = {}
            for log in self._buffer:
                level = log.get("level", "UNKNOWN")
                level_counts[level] = level_counts.get(level, 0) + 1

            return {
                "buffer_size": self.buffer_size,
                "current_size": len(self._buffer),
                "total_logs": self._total_logs,
                "dropped_logs": self._dropped_logs,
                "drop_rate": (
                    (self._dropped_logs / self._total_logs * 100)
                    if self._total_logs > 0
                    else 0
                ),
                "level_counts": level_counts,
                "overflow_strategy": self.overflow_strategy,
                "uptime_seconds": time.time() - self._last_clear,
            }


class DatabaseHandler(logging.Handler):
    """
    Async database handler with batching
    Efficiently writes logs to database with configurable batching
    """

    def __init__(
        self,
        level: int = logging.NOTSET,
        batch_size: int = 50,
        flush_interval: int = 5,
        max_queue_size: int = 10000,
        drop_on_overflow: bool = True,
    ):
        """
        Initialize database handler

        Args:
            level: Minimum log level to handle
            batch_size: Number of logs to batch before writing
            flush_interval: Seconds between automatic flushes
            max_queue_size: Maximum queue size before dropping logs
            drop_on_overflow: Whether to drop logs when queue is full
        """
        super().__init__(level)
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_queue_size = max_queue_size
        self.drop_on_overflow = drop_on_overflow

        # Use queue for async processing
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._listener_thread = None
        self._stop_event = threading.Event()

        # Statistics
        self._total_logs = 0
        self._written_logs = 0
        self._failed_logs = 0
        self._dropped_logs = 0

        self._start_listener()

    def _start_listener(self) -> None:
        """Start the queue listener for async processing"""

        def process_logs():
            batch = []
            last_flush = time.time()

            while not self._stop_event.is_set():
                try:
                    # Get log with timeout
                    timeout = max(0.1, self.flush_interval - (time.time() - last_flush))

                    try:
                        record = self._queue.get(timeout=timeout)
                        if record is not None:
                            batch.append(record)
                    except queue.Empty:
                        pass

                    now = time.time()

                    # Flush if batch is full or time elapsed
                    should_flush = len(batch) >= self.batch_size or (
                        batch and now - last_flush >= self.flush_interval
                    )

                    if should_flush:
                        self._flush_batch(batch)
                        batch.clear()
                        last_flush = now

                except Exception as e:
                    # Log error but don't break the loop
                    print(f"Database handler error: {e}")

            # Final flush on shutdown
            if batch:
                self._flush_batch(batch)

        self._listener_thread = threading.Thread(
            target=process_logs, name="DatabaseLogHandler", daemon=True
        )
        self._listener_thread.start()

    def _flush_batch(self, batch: List[logging.LogRecord]) -> None:
        """
        Flush a batch of log records to database

        Args:
            batch: List of LogRecords to write
        """
        if not batch:
            return

        db = None
        try:
            # Create a database session directly (avoiding generator issues)
            if SessionLocal is None:
                print("Warning: Database session factory not available for logging")
                self._failed_logs += len(batch)
                return
            
            db = SessionLocal()

            for record in batch:
                try:
                    # Extract fields from record
                    context = self._extract_context(record)

                    # Insert to database
                    insert_app_log(
                        db,
                        message=record.getMessage(),
                        level=record.levelname,
                        user_id=getattr(record, "user_id", None),
                        campaign_id=getattr(record, "campaign_id", None),
                        organization_id=getattr(record, "organization_id", None),
                        website_id=getattr(record, "website_id", None),
                        context=context,
                        autocommit=False,
                    )
                    self._written_logs += 1

                except Exception as e:
                    print(f"Failed to log record to database: {e}")
                    self._failed_logs += 1

            # Commit batch
            db.commit()

        except Exception as e:
            print(f"Database batch flush failed: {e}")
            self._failed_logs += len(batch)
            if db:
                try:
                    db.rollback()
                except:
                    pass
        finally:
            if db:
                try:
                    db.close()
                except:
                    pass

    def _extract_context(self, record: logging.LogRecord) -> Dict[str, Any]:
        """Extract context from LogRecord"""
        context = {}

        # List of fields to skip
        skip_fields = {
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
            "user_id",
            "campaign_id",
            "organization_id",
            "website_id",
            "getMessage",
            "message",
        }

        for key, value in record.__dict__.items():
            if not key.startswith("_") and key not in skip_fields:
                try:
                    # Ensure value is serializable
                    json.dumps(value, default=str)
                    context[key] = value
                except (TypeError, ValueError):
                    context[key] = str(value)

        # Add exception info if present
        if record.exc_info:
            context["exception"] = self.formatException(record.exc_info)

        return context

    def emit(self, record: logging.LogRecord) -> None:
        """
        Queue log record for async processing

        Args:
            record: LogRecord to process
        """
        self._total_logs += 1

        try:
            # Try to add to queue without blocking
            self._queue.put_nowait(record)
        except queue.Full:
            self._dropped_logs += 1
            if not self.drop_on_overflow:
                # If not dropping, wait for space
                try:
                    self._queue.put(record, timeout=0.1)
                except queue.Full:
                    pass
        except Exception:
            self.handleError(record)

    def flush(self) -> None:
        """Force flush any pending logs"""
        # Signal flush by adding None to queue
        try:
            self._queue.put(None, timeout=0.1)
        except:
            pass

    def close(self) -> None:
        """Close the handler and flush remaining logs"""
        # Signal listener to stop
        self._stop_event.set()

        # Wait for listener thread to finish
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=5.0)

        super().close()

    def get_stats(self) -> Dict[str, Any]:
        """
        Get handler statistics

        Returns:
            Dictionary containing handler stats
        """
        return {
            "total_logs": self._total_logs,
            "written_logs": self._written_logs,
            "failed_logs": self._failed_logs,
            "dropped_logs": self._dropped_logs,
            "queue_size": self._queue.qsize(),
            "max_queue_size": self.max_queue_size,
            "batch_size": self.batch_size,
            "flush_interval": self.flush_interval,
            "success_rate": (
                (self._written_logs / self._total_logs * 100)
                if self._total_logs > 0
                else 0
            ),
        }


# Global buffer handler instance for easy access
_global_buffer_handler: Optional[BufferHandler] = None


def get_buffer_handler() -> Optional[BufferHandler]:
    """
    Get the global buffer handler instance

    Returns:
        Global BufferHandler instance or None
    """
    return _global_buffer_handler


def set_buffer_handler(handler: BufferHandler) -> None:
    """
    Set the global buffer handler instance

    Args:
        handler: BufferHandler to set as global
    """
    global _global_buffer_handler
    _global_buffer_handler = handler


def get_recent_logs(
    limit: int = 100,
    level: Optional[str] = None,
    campaign_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Convenience function to get recent logs from global buffer

    Args:
        limit: Maximum number of logs to return
        level: Filter by log level
        campaign_id: Filter by campaign ID
        user_id: Filter by user ID

    Returns:
        List of log dictionaries
    """
    handler = get_buffer_handler()
    if not handler:
        return []

    if campaign_id:
        return handler.get_campaign_logs(campaign_id, limit, level)
    elif user_id:
        return handler.get_user_logs(user_id, limit, level)
    else:
        return handler.get_recent(limit, level)
