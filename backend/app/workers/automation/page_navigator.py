# app/workers/automation/page_navigator.py
"""Enhanced page navigation with intelligent contact page detection."""

import asyncio
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin, urlparse
from playwright.async_api import Page, Response
from app.workers.utils.logger import WorkerLogger


class NavigationResult:
    """Result of navigation attempt."""

    def __init__(
        self,
        success: bool,
        final_url: str,
        error: Optional[str] = None,
        redirected: bool = False,
        status_code: Optional[int] = None,
    ):
        self.success = success
        self.final_url = final_url
        self.error = error
        self.redirected = redirected
        self.status_code = status_code


class PageNavigator:
    """Intelligent page navigation and contact page detection."""

    def __init__(
        self, user_id: Optional[str] = None, campaign_id: Optional[str] = None
    ):
        self.logger = WorkerLogger(user_id=user_id, campaign_id=campaign_id)

        # Contact page patterns
        self.contact_patterns = [
            "contact",
            "contact-us",
            "contactus",
            "get-in-touch",
            "reach-out",
            "connect",
            "inquiry",
            "enquiry",
            "talk-to-us",
            "message",
            "feedback",
            "support",
            "reach",
            "touch",
            "write",
            "email-us",
        ]

        # Link text patterns
        self.contact_link_texts = [
            "Contact",
            "Contact Us",
            "Get in Touch",
            "Reach Out",
            "Connect",
            "Talk to Us",
            "Send Message",
            "Contact Form",
            "Drop us a line",
            "Get Started",
            "Request Info",
            "Write to Us",
            "Email Us",
            "Send Inquiry",
        ]

    async def navigate_to_url(self, page: Page, url: str) -> NavigationResult:
        """
        Navigate to URL with robust error handling.

        Handles various URL formats and retry logic.
        """
        candidates = self._get_url_variants(url)
        last_error = None

        for candidate in candidates:
            try:
                self.logger.info(f"Attempting navigation to: {candidate}")

                # Set up response handler
                response = None

                async def handle_response(resp: Response):
                    nonlocal response
                    if resp.url == candidate or resp.url.startswith(
                        candidate.rstrip("/")
                    ):
                        response = resp

                page.on("response", handle_response)

                # Navigate with timeout
                nav_response = await page.goto(
                    candidate, wait_until="domcontentloaded", timeout=30000
                )

                # Remove handler
                page.remove_listener("response", handle_response)

                # Check response status
                if nav_response:
                    status = nav_response.status

                    # Handle different status codes
                    if status >= 200 and status < 300:
                        # Success
                        final_url = page.url
                        redirected = final_url != candidate

                        self.logger.info(
                            f"✓ Navigation successful: {candidate} -> {final_url} "
                            f"(status: {status}, redirected: {redirected})"
                        )

                        return NavigationResult(
                            success=True,
                            final_url=final_url,
                            redirected=redirected,
                            status_code=status,
                        )

                    elif status >= 300 and status < 400:
                        # Redirect - should be handled automatically
                        final_url = page.url
                        self.logger.info(f"Redirected to: {final_url}")

                        return NavigationResult(
                            success=True,
                            final_url=final_url,
                            redirected=True,
                            status_code=status,
                        )

                    elif status == 403:
                        last_error = "Access forbidden (403)"
                        self.logger.warning(f"403 Forbidden for {candidate}")
                        continue

                    elif status == 404:
                        last_error = "Page not found (404)"
                        self.logger.warning(f"404 Not Found for {candidate}")
                        continue

                    elif status >= 500:
                        last_error = f"Server error ({status})"
                        self.logger.warning(f"Server error {status} for {candidate}")
                        continue

                    else:
                        last_error = f"HTTP {status}"
                        self.logger.warning(f"HTTP {status} for {candidate}")
                        continue

                # If we got here without error, consider it success
                return NavigationResult(
                    success=True,
                    final_url=page.url,
                    status_code=nav_response.status if nav_response else None,
                )

            except asyncio.TimeoutError:
                last_error = "Navigation timeout"
                self.logger.warning(f"Timeout navigating to {candidate}")
                continue

            except Exception as e:
                last_error = str(e)
                self.logger.warning(f"Navigation error for {candidate}: {e}")

                # Check if page loaded anyway
                if page.url and page.url != "about:blank":
                    self.logger.info(f"Page loaded despite error: {page.url}")
                    return NavigationResult(
                        success=True, final_url=page.url, error=f"Partial error: {e}"
                    )

                continue

        # All attempts failed
        return NavigationResult(
            success=False,
            final_url=url,
            error=last_error or "All navigation attempts failed",
        )

    def _get_url_variants(self, url: str) -> List[str]:
        """Generate URL variants to try."""
        variants = []

        # Clean the URL
        url = url.strip()

        # Parse URL
        parsed = urlparse(url)

        if parsed.scheme:
            # URL already has scheme
            variants.append(url)

            # Try with/without www
            if parsed.netloc.startswith("www."):
                no_www = url.replace("://www.", "://", 1)
                variants.append(no_www)
            else:
                with_www = url.replace("://", "://www.", 1)
                variants.append(with_www)
        else:
            # No scheme, try both http and https
            # Clean domain (remove any leading www.)
            domain = url.replace("www.", "", 1) if url.startswith("www.") else url

            variants.extend(
                [
                    f"https://{domain}",
                    f"https://www.{domain}",
                    f"http://{domain}",
                    f"http://www.{domain}",
                ]
            )

        # Remove duplicates while preserving order
        seen = set()
        unique_variants = []
        for v in variants:
            if v not in seen:
                seen.add(v)
                unique_variants.append(v)

        return unique_variants

    async def wait_for_dynamic_content(self, page: Page):
        """
        Wait for dynamic content to load.

        Uses multiple strategies to ensure content is ready.
        """
        try:
            # Wait for basic load states
            await page.wait_for_load_state("domcontentloaded", timeout=10000)

            # Try to wait for network idle (soft fail)
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except:
                self.logger.info("Network didn't reach idle state, continuing...")

            # Wait for common elements that indicate content is loaded
            element_selectors = [
                "form",
                "input",
                "textarea",
                "button",
                "main",
                "article",
                "#content",
                ".content",
                "[role='main']",
            ]

            for selector in element_selectors:
                try:
                    await page.wait_for_selector(
                        selector, timeout=3000, state="attached"
                    )
                    break
                except:
                    continue

            # Wait for JavaScript frameworks to initialize
            await self._wait_for_javascript_frameworks(page)

            # Additional wait for dynamic content
            await asyncio.sleep(2)

            self.logger.info("Dynamic content loading complete")

        except Exception as e:
            self.logger.warning(f"Error waiting for dynamic content: {e}")

    async def _wait_for_javascript_frameworks(self, page: Page):
        """Wait for common JavaScript frameworks to initialize."""
        try:
            # Check for React
            react_ready = await page.evaluate(
                """
                () => {
                    return typeof React !== 'undefined' || 
                           document.querySelector('[data-reactroot]') !== null ||
                           document.querySelector('#root') !== null;
                }
            """
            )

            if react_ready:
                await asyncio.sleep(1)  # Extra wait for React

            # Check for Angular
            angular_ready = await page.evaluate(
                """
                () => {
                    return typeof angular !== 'undefined' ||
                           document.querySelector('[ng-app]') !== null ||
                           document.querySelector('[data-ng-app]') !== null;
                }
            """
            )

            if angular_ready:
                await asyncio.sleep(1)  # Extra wait for Angular

            # Check for Vue
            vue_ready = await page.evaluate(
                """
                () => {
                    return typeof Vue !== 'undefined' ||
                           document.querySelector('[data-v-]') !== null ||
                           document.querySelector('#app') !== null;
                }
            """
            )

            if vue_ready:
                await asyncio.sleep(1)  # Extra wait for Vue

        except:
            pass  # Framework detection is optional

    # Add to page_navigator.py
    async def find_contact_page(self, page: Page) -> Optional[str]:
        """Enhanced contact page detection."""

        # Priority 1: Check navigation menu
        nav_contact = await self._find_contact_in_navigation(page)
        if nav_contact:
            return nav_contact

        # Priority 2: Check footer (often has contact link)
        footer_contact = await self._find_contact_in_footer(page)
        if footer_contact:
            return footer_contact

        # Priority 3: Check all visible links
        contact_patterns = [
            "contact",
            "contact-us",
            "get-in-touch",
            "reach-out",
            "connect",
            "talk-to-us",
        ]

        for pattern in contact_patterns:
            selector = f'a[href*="{pattern}" i]'
            links = await page.query_selector_all(selector)

            for link in links:
                if await link.is_visible():
                    href = await link.get_attribute("href")
                    if href:
                        full_url = urljoin(page.url, href)
                        return full_url

        return None

    async def _find_contact_in_navigation(self, page: Page) -> Optional[str]:
        """Find contact link in navigation menu."""
        nav_selectors = [
            "nav",
            "header",
            "[role='navigation']",
            ".navigation",
            ".navbar",
            ".menu",
            "#menu",
            ".nav",
            ".header-menu",
            ".main-menu",
        ]

        for nav_selector in nav_selectors:
            try:
                nav_element = await page.query_selector(nav_selector)
                if nav_element:
                    # Look for contact links within navigation
                    for pattern in self.contact_patterns[:5]:  # Check top patterns
                        link = await nav_element.query_selector(
                            f'a[href*="{pattern}" i]'
                        )
                        if link and await link.is_visible():
                            href = await link.get_attribute("href")
                            if href:
                                return urljoin(page.url, href)

            except:
                continue

        return None

    async def _find_contact_in_footer(self, page: Page) -> Optional[str]:
        """Find contact link in footer."""
        footer_selectors = [
            "footer",
            "[role='contentinfo']",
            ".footer",
            "#footer",
            ".site-footer",
        ]

        for footer_selector in footer_selectors:
            try:
                footer_element = await page.query_selector(footer_selector)
                if footer_element:
                    # Look for contact links within footer
                    for pattern in self.contact_patterns[:5]:  # Check top patterns
                        link = await footer_element.query_selector(
                            f'a[href*="{pattern}" i]'
                        )
                        if link:
                            href = await link.get_attribute("href")
                            if href:
                                return urljoin(page.url, href)

            except:
                continue

        return None

    async def check_page_accessibility(self, page: Page) -> Dict[str, Any]:
        """Check if page is accessible and not blocked."""
        accessibility = {
            "accessible": True,
            "issues": [],
            "requires_auth": False,
            "cloudflare_protected": False,
            "captcha_present": False,
            "blocked": False,
        }

        try:
            # Get page content
            page_text = ""
            try:
                page_text = (await page.inner_text("body")).lower()
            except:
                # If we can't get body text, page might be blocked
                accessibility["blocked"] = True
                accessibility["issues"].append("Cannot access page content")
                accessibility["accessible"] = False
                return accessibility

            # Check for authentication requirements
            auth_indicators = [
                "login",
                "sign in",
                "authentication required",
                "please log in",
                "unauthorized",
                "401",
                "access denied",
                "forbidden",
            ]

            for indicator in auth_indicators:
                if indicator in page_text:
                    accessibility["requires_auth"] = True
                    accessibility["issues"].append("Authentication required")
                    accessibility["accessible"] = False
                    break

            # Check for Cloudflare protection
            if "cloudflare" in page_text or await page.query_selector("#cf-wrapper"):
                accessibility["cloudflare_protected"] = True
                accessibility["issues"].append("Cloudflare protection detected")
                accessibility["accessible"] = False

            # Check for various CAPTCHA types
            captcha_selectors = [
                ".g-recaptcha",
                "#recaptcha",
                "[data-sitekey]",
                ".h-captcha",
                ".captcha",
                "iframe[src*='recaptcha']",
                "iframe[src*='hcaptcha']",
                "[data-captcha]",
            ]

            for selector in captcha_selectors:
                if await page.query_selector(selector):
                    accessibility["captcha_present"] = True
                    accessibility["issues"].append("CAPTCHA detected")
                    break

            # Check for bot detection
            bot_indicators = [
                "bot detected",
                "automated traffic",
                "suspicious activity",
                "please verify you are human",
                "access restricted",
            ]

            for indicator in bot_indicators:
                if indicator in page_text:
                    accessibility["blocked"] = True
                    accessibility["issues"].append("Bot detection triggered")
                    accessibility["accessible"] = False
                    break

        except Exception as e:
            accessibility["issues"].append(f"Error checking accessibility: {e}")
            accessibility["accessible"] = False

        return accessibility
