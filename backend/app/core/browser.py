# app/core/browser.py - Optimized browser management with smart logging
from __future__ import annotations

import os
import asyncio
import time
from typing import (
    Optional,
    Dict,
    Any,
    List,
    Literal,
    Union,
    Callable,
    Awaitable,
    Any,
)
from app.logging import get_logger

logger = get_logger(__name__)

# ---- Env flags --------------------------------------------------------------
ENABLE_BROWSER = os.getenv("FEATURE_USE_BROWSER", "true").lower() != "false"
HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() != "false"
SLOW_MO_MS = int(os.getenv("BROWSER_SLOW_MO_MS", "0") or "0")
# ---------------------------------------------------------------------------

_browser = None  # type: ignore
_playwright = None  # type: ignore
_lock = asyncio.Lock()
_page_count = 0
_context_count = 0


async def get_browser():
    """Lazily start Playwright + Chromium when first needed."""
    if not ENABLE_BROWSER:
        logger.warning(
            "Browser access attempted but disabled",
            extra={"event": "browser_disabled", "config": "FEATURE_USE_BROWSER=false"},
        )
        raise RuntimeError("Browser disabled by FEATURE_USE_BROWSER=false")

    global _browser, _playwright
    if _browser:
        return _browser

    async with _lock:
        if _browser:
            return _browser

        start_time = time.time()
        try:
            from playwright.async_api import async_playwright  # type: ignore

            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                headless=HEADLESS,
                slow_mo=SLOW_MO_MS if SLOW_MO_MS > 0 else 0,
            )

            duration_ms = (time.time() - start_time) * 1000

            # Log browser initialization (happens once per app lifecycle)
            logger.info(
                "Browser initialized",
                extra={
                    "event": "browser_init",
                    "duration_ms": round(duration_ms, 2),
                    "headless": HEADLESS,
                    "slow_mo_ms": SLOW_MO_MS,
                },
            )

            return _browser

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000

            logger.error(
                "Browser initialization failed",
                extra={
                    "event": "browser_init_failed",
                    "duration_ms": round(duration_ms, 2),
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "headless": HEADLESS,
                },
                exc_info=True,
            )
            raise RuntimeError(f"Failed to start browser: {e}") from e


async def new_page(**kwargs):
    """Create a new browser page with optional configuration."""
    global _page_count, _context_count

    start_time = time.time()
    context = None
    page = None

    try:
        browser = await get_browser()
        context = await browser.new_context()
        _context_count += 1

        page = await context.new_page()
        _page_count += 1

        if "user_agent" in kwargs:
            await context.set_extra_http_headers({"User-Agent": kwargs["user_agent"]})

        # Only log if page creation is slow (>500ms) or has custom config
        duration_ms = (time.time() - start_time) * 1000

        if duration_ms > 500 or kwargs:
            logger.info(
                "Browser page created",
                extra={
                    "event": "browser_page_created",
                    "duration_ms": round(duration_ms, 2),
                    "has_custom_ua": "user_agent" in kwargs,
                    "total_pages": _page_count,
                    "total_contexts": _context_count,
                },
            )

        return page

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Browser page creation failed",
            extra={
                "event": "browser_page_failed",
                "duration_ms": round(duration_ms, 2),
                "error_type": type(e).__name__,
                "error_message": str(e),
                "has_custom_config": bool(kwargs),
            },
            exc_info=True,
        )

        # Cleanup if partially created
        try:
            if context:
                await context.close()
        except:
            pass

        raise


async def with_page(fn: Callable[..., Awaitable[Any]], *args, **kwargs) -> Any:
    """Execute a function with a managed browser page context."""
    global _page_count, _context_count

    start_time = time.time()
    context = None
    page = None

    try:
        browser = await get_browser()
        context = await browser.new_context()
        _context_count += 1

        page = await context.new_page()
        _page_count += 1

        # Execute the function
        result = await fn(page, *args, **kwargs)

        # Only log if operation is slow (>2s) to track performance issues
        duration_ms = (time.time() - start_time) * 1000

        if duration_ms > 2000:
            logger.info(
                "Browser operation completed (slow)",
                extra={
                    "event": "browser_operation_slow",
                    "duration_ms": round(duration_ms, 2),
                    "function": fn.__name__,
                    "total_pages": _page_count,
                },
            )

        return result

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Browser operation failed",
            extra={
                "event": "browser_operation_failed",
                "duration_ms": round(duration_ms, 2),
                "function": fn.__name__,
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )
        raise

    finally:
        # Always cleanup the context
        if context:
            try:
                await context.close()
                _context_count -= 1
            except Exception as cleanup_error:
                # Only log cleanup failures
                logger.warning(
                    "Browser context cleanup failed",
                    extra={
                        "event": "browser_cleanup_failed",
                        "error_type": type(cleanup_error).__name__,
                    },
                )


async def close_browser():
    """Shutdown the browser and cleanup resources."""
    global _browser, _playwright, _page_count, _context_count

    if not _browser and not _playwright:
        return  # Nothing to close

    start_time = time.time()

    try:
        if _browser:
            await _browser.close()
            _browser = None

        if _playwright:
            await _playwright.stop()
            _playwright = None

        duration_ms = (time.time() - start_time) * 1000

        # Log browser shutdown (happens on app shutdown)
        logger.info(
            "Browser closed",
            extra={
                "event": "browser_closed",
                "duration_ms": round(duration_ms, 2),
                "total_pages_created": _page_count,
                "final_context_count": _context_count,
            },
        )

        # Reset counters
        _page_count = 0
        _context_count = 0

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            "Browser shutdown failed",
            extra={
                "event": "browser_close_failed",
                "duration_ms": round(duration_ms, 2),
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
            exc_info=True,
        )

        # Force reset even on error
        _browser = None
        _playwright = None
        _page_count = 0
        _context_count = 0
