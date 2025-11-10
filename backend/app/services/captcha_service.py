# app/services/captcha_service.py
"""Enhanced CAPTCHA detection and solving service with user profile integration."""

import asyncio
import base64
import json
import logging
import os
import requests
from typing import Optional, Dict, Any, Tuple
from playwright.async_api import Page
from sqlalchemy.orm import Session

from app.services.log_service import LogService
from app.models.user_profile import UserProfile

logger = logging.getLogger(__name__)


class DeathByCaptchaAPI:
    """Death By Captcha API client with user-specific credentials."""

    def __init__(self, username: str = "", password: str = ""):
        self.username = username
        self.password = password
        self.enabled = bool(self.username and self.password)
        self.base_url = "http://api.dbcapi.me/api"

        if self.enabled:
            logger.info("Death By Captcha client initialized with user credentials")
        else:
            logger.warning(
                "Death By Captcha credentials not provided - CAPTCHA solving disabled"
            )

    @classmethod
    def from_user_profile(cls, db: Session, user_id: str):
        """Create DBC client from user profile credentials."""
        try:
            profile = (
                db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
            )

            if profile and profile.dbc_username and profile.dbc_password:
                return cls(username=profile.dbc_username, password=profile.dbc_password)
            else:
                logger.info(f"No DBC credentials found for user {user_id}")
                return cls()  # Return disabled client

        except Exception as e:
            logger.error(f"Error loading DBC credentials for user {user_id}: {e}")
            return cls()  # Return disabled client

    async def get_balance(self) -> float:
        """Get account balance."""
        if not self.enabled:
            return 0.0

        try:
            response = requests.post(
                f"{self.base_url}/user",
                data={"username": self.username, "password": self.password},
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()
                balance = float(result.get("balance", 0)) / 100  # Convert from cents
                logger.info(f"DBC Balance: ${balance:.2f}")
                return balance
            else:
                logger.error(f"DBC balance check failed: HTTP {response.status_code}")

        except Exception as e:
            logger.error(f"Error getting DBC balance: {e}")

        return 0.0

    async def solve_image_captcha(self, image_data: bytes) -> Optional[str]:
        """Solve image-based CAPTCHA."""
        if not self.enabled:
            logger.warning("DBC not enabled - cannot solve CAPTCHA")
            return None

        try:
            # Check balance first
            balance = await self.get_balance()
            if balance < 0.01:  # $0.01 minimum
                logger.error(f"Insufficient DBC balance: ${balance:.2f}")
                return None

            # Upload CAPTCHA
            upload_data = {
                "username": self.username,
                "password": self.password,
                "captchafile": base64.b64encode(image_data).decode("utf-8"),
            }

            logger.info("Uploading CAPTCHA to Death By Captcha...")
            response = requests.post(
                f"{self.base_url}/captcha", data=upload_data, timeout=30
            )

            if response.status_code != 200:
                logger.error(f"CAPTCHA upload failed: HTTP {response.status_code}")
                return None

            result = response.json()
            if not result.get("captcha"):
                logger.error("No captcha ID returned from DBC")
                return None

            captcha_id = result["captcha"]
            logger.info(f"CAPTCHA uploaded with ID: {captcha_id}")

            # Poll for solution (max 5 minutes)
            for attempt in range(60):
                await asyncio.sleep(5)

                try:
                    poll_response = requests.get(
                        f"{self.base_url}/captcha/{captcha_id}", timeout=10
                    )

                    if poll_response.status_code == 200:
                        poll_result = poll_response.json()
                        if poll_result.get("text"):
                            solution = poll_result["text"]
                            logger.info(
                                f"CAPTCHA solved: '{solution}' (attempt {attempt + 1})"
                            )
                            return solution
                        elif poll_result.get("is_correct") == False:
                            logger.error("CAPTCHA marked as incorrectly solved")
                            return None

                except Exception as e:
                    logger.warning(f"Polling attempt {attempt + 1} failed: {e}")

            logger.error("CAPTCHA solving timeout (5 minutes)")
            return None

        except Exception as e:
            logger.error(f"CAPTCHA solving error: {e}")
            return None

    async def solve_recaptcha_v2(
        self,
        site_key: str,
        page_url: str,
        proxy: Optional[Dict[str, str]] = None,
        max_attempts: int = 60,
        poll_interval: int = 5,
    ) -> Optional[Tuple[str, str]]:
        """Solve reCAPTCHA v2 using Death By Captcha token API."""
        if not self.enabled:
            logger.warning("DBC not enabled - cannot solve reCAPTCHA v2")
            return None

        try:
            # Optional: ensure we have some balance
            balance = await self.get_balance()
            if balance < 0.05:
                logger.error(f"Insufficient DBC balance for token solving: ${balance:.2f}")
                return None

            token_params = {
                "googlekey": site_key,
                "pageurl": page_url,
            }

            if proxy and proxy.get("url"):
                token_params["proxy"] = proxy["url"]
                token_params["proxytype"] = proxy.get("type", "HTTP").upper()

            payload = {
                "username": self.username,
                "password": self.password,
                "type": 4,  # Token-based captcha
                "token_params": json.dumps(token_params),
            }

            logger.info("Submitting reCAPTCHA v2 token request to Death By Captcha")
            response = requests.post(
                f"{self.base_url}/captcha",
                data=payload,
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(
                    "reCAPTCHA token submission failed: HTTP %s - %s",
                    response.status_code,
                    response.text,
                )
                return None

            result = response.json()
            captcha_id = result.get("captcha")

            if not captcha_id:
                logger.error("Death By Captcha did not return captcha ID for token request")
                return None

            logger.info(f"Death By Captcha token request accepted, ID: {captcha_id}")

            for attempt in range(max_attempts):
                await asyncio.sleep(poll_interval)
                try:
                    poll_response = requests.get(
                        f"{self.base_url}/captcha/{captcha_id}",
                        timeout=15,
                    )

                    if poll_response.status_code != 200:
                        logger.warning(
                            "Token poll failed (attempt %s): HTTP %s",
                            attempt + 1,
                            poll_response.status_code,
                        )
                        continue

                    poll_result = poll_response.json()
                    text = poll_result.get("text")

                    if text:
                        logger.info("reCAPTCHA token received from Death By Captcha")
                        return captcha_id, text

                    if poll_result.get("is_correct") is False:
                        logger.error("Death By Captcha marked token as incorrect")
                        break

                except Exception as poll_error:
                    logger.warning(
                        "Error polling reCAPTCHA token (attempt %s): %s",
                        attempt + 1,
                        poll_error,
                    )

            logger.error("Timed out waiting for reCAPTCHA token from Death By Captcha")
            return None

        except Exception as e:
            logger.error(f"reCAPTCHA solving error: {e}")
            return None

    async def report_incorrect(self, captcha_id: str) -> bool:
        """Report incorrectly solved CAPTCHA for refund."""
        if not self.enabled:
            return False

        try:
            response = requests.post(
                f"{self.base_url}/captcha/{captcha_id}/report",
                data={"username": self.username, "password": self.password},
                timeout=10,
            )

            success = response.status_code == 200
            if success:
                logger.info(f"Reported incorrect CAPTCHA: {captcha_id}")
            else:
                logger.error(
                    f"Failed to report incorrect CAPTCHA: HTTP {response.status_code}"
                )

            return success

        except Exception as e:
            logger.error(f"Error reporting incorrect CAPTCHA: {e}")
            return False


class CaptchaService:
    """Enhanced CAPTCHA detection and solving service with user profile integration."""

    def __init__(
        self, db: Session = None, user_id: str = None, campaign_id: str = None
    ):
        self.db = db
        self.user_id = user_id
        self.campaign_id = campaign_id

        # Initialize DBC client with user credentials
        if db and user_id:
            self.dbc = DeathByCaptchaAPI.from_user_profile(db, user_id)
        else:
            # Fallback to environment variables for testing
            self.dbc = DeathByCaptchaAPI(
                username=os.getenv("DBC_USERNAME", "ScoopCPS"),
                password=os.getenv("DBC_PASSWORD", "CowGoesThud@3030!"),
            )

        # CAPTCHA type detection patterns
        self.captcha_patterns = {
            "recaptcha_v2": [
                ".g-recaptcha",
                "#g-recaptcha",
                'iframe[src*="recaptcha"]',
                "[data-sitekey]",
            ],
            "recaptcha_v3": [
                'script[src*="recaptcha/releases/"]',
                "grecaptcha.execute",
            ],
            "hcaptcha": [
                ".h-captcha",
                "#h-captcha",
                'iframe[src*="hcaptcha"]',
                "[data-hcaptcha-sitekey]",
            ],
            "turnstile": [
                ".cf-turnstile",
                "#cf-turnstile",
                'script[src*="challenges.cloudflare.com"]',
            ],
            "image_captcha": [
                'img[src*="captcha" i]',
                'img[alt*="captcha" i]',
                'canvas[id*="captcha" i]',
                ".captcha-image",
            ],
            "text_captcha": [
                'input[name*="captcha" i]',
                'input[placeholder*="captcha" i]',
                'label:has-text("captcha")',
            ],
        }

    def _log_info(self, message: str, **context):
        """Log info message."""
        LogService.info(
            message, user_id=self.user_id, campaign_id=self.campaign_id, context=context
        )
        logger.info(f"[CAPTCHA] {message}")

    def _log_warning(self, message: str, **context):
        """Log warning message."""
        LogService.warning(
            message, user_id=self.user_id, campaign_id=self.campaign_id, context=context
        )
        logger.warning(f"[CAPTCHA] {message}")

    def _log_error(self, message: str, **context):
        """Log error message."""
        LogService.error(
            message, user_id=self.user_id, campaign_id=self.campaign_id, context=context
        )
        logger.error(f"[CAPTCHA] {message}")

    async def detect_captcha_types(self, page: Page) -> Dict[str, bool]:
        """Detect all CAPTCHA types present on the page."""
        detected = {}

        for captcha_type, selectors in self.captcha_patterns.items():
            detected[captcha_type] = False

            for selector in selectors:
                try:
                    if selector.startswith("script"):
                        # Check for script-based CAPTCHAs
                        scripts = await page.query_selector_all("script")
                        for script in scripts:
                            src = await script.get_attribute("src")
                            content = await script.inner_text()

                            if (src and "recaptcha" in src) or (
                                "grecaptcha" in content
                            ):
                                detected[captcha_type] = True
                                break
                    else:
                        # Check for element-based CAPTCHAs
                        element = await page.query_selector(selector)
                        if element:
                            is_visible = await element.is_visible()
                            if is_visible:
                                detected[captcha_type] = True
                                break

                except Exception as e:
                    self._log_warning(f"Error checking selector '{selector}': {e}")
                    continue

                if detected[captcha_type]:
                    break

        # Log detected CAPTCHAs
        found_types = [t for t, detected in detected.items() if detected]
        if found_types:
            self._log_info(f"Detected CAPTCHA types: {', '.join(found_types)}")

        return detected

    async def solve_if_present(self, page: Page, timeout_ms: int = 30000) -> bool:
        """Detect and solve CAPTCHA if present."""
        try:
            detected_types = await self.detect_captcha_types(page)

            # No CAPTCHAs detected
            if not any(detected_types.values()):
                return True  # No CAPTCHA to solve = success

            self._log_info("CAPTCHA detected, attempting to solve...")

            # Check if user has DBC credentials
            if not self.dbc.enabled:
                if self.user_id:
                    self._log_warning(
                        "User has not configured Death By Captcha credentials"
                    )
                else:
                    self._log_warning("No Death By Captcha credentials available")
                return False

            # Solve image CAPTCHAs first (most reliable)
            if detected_types.get("image_captcha"):
                success = await self._solve_image_captcha(page)
                if success:
                    await self._log_captcha_success("image_captcha")
                    return True
                else:
                    await self._log_captcha_failure("image_captcha")

            # Handle other CAPTCHA types
            if detected_types.get("recaptcha_v2"):
                return await self._handle_recaptcha_v2(page)

            if detected_types.get("hcaptcha"):
                self._log_warning(
                    "hCaptcha detected - manual intervention may be required"
                )
                return await self._handle_hcaptcha(page)

            if detected_types.get("turnstile"):
                self._log_warning(
                    "Turnstile detected - waiting for automatic resolution"
                )
                return await self._handle_turnstile(page)

            return False

        except Exception as e:
            self._log_error(f"CAPTCHA solving error: {e}")
            return False

    async def _solve_image_captcha(self, page: Page) -> bool:
        """Solve image-based CAPTCHA."""
        try:
            # Find CAPTCHA image
            image_selectors = [
                'img[src*="captcha" i]',
                'img[alt*="captcha" i]',
                ".captcha-image img",
                'canvas[id*="captcha" i]',
            ]

            captcha_element = None
            for selector in image_selectors:
                captcha_element = await page.query_selector(selector)
                if captcha_element:
                    is_visible = await captcha_element.is_visible()
                    if is_visible:
                        break

            if not captcha_element:
                self._log_warning("Image CAPTCHA element not found")
                return False

            self._log_info("Taking screenshot of CAPTCHA image")

            # Take screenshot of CAPTCHA
            captcha_image = await captcha_element.screenshot()

            # Solve with Death By Captcha
            solution = await self.dbc.solve_image_captcha(captcha_image)

            if not solution:
                self._log_error("Failed to solve CAPTCHA")
                return False

            # Find input field and enter solution
            input_selectors = [
                'input[name*="captcha" i]',
                'input[placeholder*="captcha" i]',
                'input[id*="captcha" i]',
                'input[type="text"]:near(img[src*="captcha"])',
            ]

            captcha_input = None
            for selector in input_selectors:
                captcha_input = await page.query_selector(selector)
                if captcha_input:
                    is_visible = await captcha_input.is_visible()
                    if is_visible:
                        break

            if not captcha_input:
                self._log_error("CAPTCHA input field not found")
                return False

            # Enter solution
            await captcha_input.fill(solution)
            self._log_info(f"Entered CAPTCHA solution: {solution}")

            # Optional: wait a moment for validation
            await asyncio.sleep(1)

            return True

        except Exception as e:
            self._log_error(f"Image CAPTCHA solving error: {e}")
            return False

    async def _handle_recaptcha_v2(self, page: Page) -> bool:
        """Handle reCAPTCHA v2."""
        try:
            self._log_info("Attempting to solve reCAPTCHA v2 via Death By Captcha")

            site_key = await page.evaluate(
                """
                () => {
                    const explicit = document.querySelector('[data-sitekey]');
                    if (explicit && explicit.getAttribute("data-sitekey")) {
                        return explicit.getAttribute("data-sitekey");
                    }
                    const iframe = document.querySelector('iframe[src*="recaptcha"]');
                    if (iframe) {
                        const src = iframe.getAttribute("src") || "";
                        const match = src.match(/[?&]k=([^&]+)/);
                        if (match && match[1]) {
                            return decodeURIComponent(match[1]);
                        }
                    }
                    return null;
                }
            """
            )

            if not site_key:
                self._log_warning("Unable to extract reCAPTCHA site key")
                return False

            dbc_result = await self.dbc.solve_recaptcha_v2(
                site_key=site_key,
                page_url=page.url,
            )

            if not dbc_result:
                self._log_error("Death By Captcha failed to provide reCAPTCHA token")
                return False

            captcha_id, token = dbc_result

            # Inject token into page
            await page.evaluate(
                """
                (token) => {
                    const textarea = document.querySelector('[name="g-recaptcha-response"]');
                    if (textarea) {
                        textarea.value = token;
                        textarea.dispatchEvent(new Event("change", { bubbles: true }));
                    } else {
                        const form = document.querySelector("form");
                        if (form) {
                            const hidden = document.createElement("textarea");
                            hidden.name = "g-recaptcha-response";
                            hidden.style.display = "none";
                            hidden.value = token;
                            form.appendChild(hidden);
                        }
                    }
                    if (window.grecaptcha && window.grecaptcha.getResponse) {
                        try {
                            const widgets = window.grecaptcha.render ? window.grecaptcha.renderedIDs || [] : [];
                            widgets.forEach((id) => {
                                window.grecaptcha.setResponse(id, token);
                            });
                        } catch (err) {
                            console.debug("Failed to set grecaptcha response", err);
                        }
                    }
                }
            """,
                token,
            )

            await asyncio.sleep(1.5)

            # Verify token presence
            token_check = await page.evaluate(
                """
                () => {
                    const response = document.querySelector('[name="g-recaptcha-response"]');
                    return response ? response.value.length > 0 : false;
                }
            """
            )

            if token_check:
                self._log_info("reCAPTCHA v2 token successfully injected")
                await self._log_captcha_success("recaptcha_v2")
                return True

            await self._log_captcha_failure(
                "recaptcha_v2",
                error="Token injection verification failed",
            )
            self._log_warning("reCAPTCHA token injection failed verification")
            return False

        except Exception as e:
            self._log_error(f"reCAPTCHA handling error: {e}")
            return False

    async def _handle_hcaptcha(self, page: Page) -> bool:
        """Handle hCaptcha."""
        try:
            self._log_info("Waiting for hCaptcha resolution...")
            await asyncio.sleep(5)

            # Check if hCaptcha token is present
            token_check = await page.evaluate(
                """
                () => {
                    const response = document.querySelector('[name="h-captcha-response"]');
                    return response ? response.value.length > 0 : false;
                }
            """
            )

            if token_check:
                self._log_info("hCaptcha appears to be solved")
                return True

            self._log_warning("hCaptcha not solved")
            return False

        except Exception as e:
            self._log_error(f"hCaptcha handling error: {e}")
            return False

    async def _handle_turnstile(self, page: Page) -> bool:
        """Handle Cloudflare Turnstile."""
        try:
            self._log_info("Waiting for Turnstile automatic resolution...")
            await asyncio.sleep(10)

            # Check if Turnstile token is present
            token_check = await page.evaluate(
                """
                () => {
                    const response = document.querySelector('[name="cf-turnstile-response"]');
                    return response ? response.value.length > 0 : false;
                }
            """
            )

            if token_check:
                self._log_info("Turnstile resolved successfully")
                return True

            self._log_warning("Turnstile not resolved")
            return False

        except Exception as e:
            self._log_error(f"Turnstile handling error: {e}")
            return False

    async def _log_captcha_success(self, captcha_type: str):
        """Log successful CAPTCHA solving to database."""
        if not self.db:
            return

        try:
            from app.models.logs import CaptchaLog
            import uuid
            from datetime import datetime

            log_entry = CaptchaLog(
                id=uuid.uuid4(),
                submission_id=None,  # Will be set by calling code if available
                captcha_type=captcha_type,
                solved=True,
                solve_time=None,  # Could track this if needed
                dbc_balance=await self.dbc.get_balance() if self.dbc.enabled else 0.0,
                error=None,
                timestamp=datetime.utcnow(),
            )

            self.db.add(log_entry)
            self.db.commit()

        except Exception as e:
            logger.error(f"Error logging CAPTCHA success: {e}")

    async def _log_captcha_failure(self, captcha_type: str, error: str = None):
        """Log failed CAPTCHA solving to database."""
        if not self.db:
            return

        try:
            from app.models.logs import CaptchaLog
            import uuid
            from datetime import datetime

            log_entry = CaptchaLog(
                id=uuid.uuid4(),
                submission_id=None,  # Will be set by calling code if available
                captcha_type=captcha_type,
                solved=False,
                solve_time=None,
                dbc_balance=await self.dbc.get_balance() if self.dbc.enabled else 0.0,
                error=error or "CAPTCHA solving failed",
                timestamp=datetime.utcnow(),
            )

            self.db.add(log_entry)
            self.db.commit()

        except Exception as e:
            logger.error(f"Error logging CAPTCHA failure: {e}")

    async def verify_solution(
        self, page: Page, expected_success_indicators: list = None
    ) -> bool:
        """Verify if CAPTCHA solution was accepted."""
        try:
            await asyncio.sleep(3)

            # Check for error indicators
            error_indicators = [
                "incorrect captcha",
                "invalid captcha",
                "captcha failed",
                "wrong captcha",
                "captcha error",
            ]

            page_content = await page.content()
            page_text = page_content.lower()

            for indicator in error_indicators:
                if indicator in page_text:
                    self._log_error(f"CAPTCHA verification failed: {indicator}")
                    return False

            # Check for success indicators if provided
            if expected_success_indicators:
                for indicator in expected_success_indicators:
                    if indicator.lower() in page_text:
                        self._log_info(f"CAPTCHA verification success: {indicator}")
                        return True

            # If no explicit error found, assume success
            self._log_info("CAPTCHA solution appears to be accepted")
            return True

        except Exception as e:
            self._log_error(f"CAPTCHA verification error: {e}")
            return False
