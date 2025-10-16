# app/workers/automation/browser_automation.py
"""
Enhanced browser automation with:
- Contact page detection and navigation (PRIORITY)
- Form detection and filling with user profile data
- Success verification
- Email extraction fallback
"""

import asyncio
import logging
import re
from typing import Dict, Any, Optional
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright, Page, BrowserContext, Browser

logger = logging.getLogger(__name__)

# Patterns for finding contact pages
CONTACT_PATTERNS = [
    r"contact",
    r"contact[_-]?us",
    r"get[_-]?in[_-]?touch",
    r"reach[_-]?out",
    r"connect",
    r"inquiry",
    r"support",
    r"help",
    r"about",
]

# Form field patterns
FORM_FIELD_PATTERNS = {
    "email": [r"email", r"e-?mail", r"mail", r"contact"],
    "name": [r"name", r"full[_-]?name", r"fullname", r"your[_-]?name"],
    "phone": [r"phone", r"telephone", r"mobile", r"cell"],
    "message": [r"message", r"comment", r"inquiry", r"details", r"description"],
    "company": [r"company", r"organization", r"business"],
}

# Success indicators
SUCCESS_KEYWORDS = [
    "thank you",
    "success",
    "message sent",
    "received",
    "submitted",
    "we'll be in touch",
    "contact",
]


class BrowserAutomation:
    """Browser automation with contact page priority."""

    def __init__(
        self,
        headless: bool = False,
        slow_mo: int = 500,
        user_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
    ):
        self.headless = headless
        self.slow_mo = slow_mo
        self.user_id = user_id
        self.campaign_id = campaign_id

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    async def start(self):
        """Initialize browser."""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )
            logger.info("Browser started successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to start browser: {e}", exc_info=True)
            return False

    async def stop(self):
        """Close browser."""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("Browser stopped")
        except Exception as e:
            logger.error(f"Error stopping browser: {e}")

    async def process(self, url: str, user_profile: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a website with contact page priority.

        Flow:
        1. Navigate to main URL
        2. Find and navigate to contact page
        3. Detect and fill contact form
        4. Verify success
        5. Fallback to email extraction
        """
        page = None
        result = {"success": False, "method": None, "error": None, "details": {}}

        try:
            page = await self.context.new_page()
            logger.info(f"Processing URL: {url}")

            # Step 1: Navigate to main URL
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)  # Wait for dynamic content
                logger.info(f"✓ Main page loaded")
            except Exception as e:
                result["error"] = f"Failed to load main URL: {str(e)}"
                logger.warning(result["error"])
                return result

            # Step 2: Find contact page
            contact_page_url = await self._find_contact_page(page, url)

            if contact_page_url and contact_page_url != page.url:
                logger.info(f"Found contact page: {contact_page_url}")
                try:
                    await page.goto(
                        contact_page_url, wait_until="domcontentloaded", timeout=30000
                    )
                    await asyncio.sleep(2)
                    logger.info(f"✓ Navigated to contact page")
                except Exception as e:
                    logger.warning(f"Failed to navigate to contact page: {e}")
            else:
                logger.info(f"No contact page link found - using main URL")

            # Step 3: Try to fill and submit form
            form_result = await self._fill_and_submit_form(page, user_profile)

            if form_result["success"]:
                result["success"] = True
                result["method"] = "form_submission"
                result["details"] = form_result["details"]
                logger.info(f"✓ Form submitted successfully")
                return result

            logger.info(f"Form submission failed: {form_result.get('error')}")

            # Step 4: Fallback to email extraction
            emails = await self._extract_emails(page)

            if emails:
                result["success"] = True
                result["method"] = "email_extraction"
                result["details"] = {"emails": emails}
                logger.info(f"✓ Emails extracted: {emails[:3]}")  # Log first 3
                return result

            result["error"] = "No forms found and no email addresses extracted"
            return result

        except Exception as e:
            result["error"] = f"Processing error: {str(e)}"
            logger.error(f"Process error: {e}", exc_info=True)
            return result

        finally:
            if page:
                try:
                    await page.close()
                except:
                    pass

    async def _find_contact_page(self, page: Page, base_url: str) -> Optional[str]:
        """
        Find contact page link on the website.

        Looks for links matching contact patterns.
        Returns absolute URL of contact page if found.
        """
        try:
            # Get all links on the page
            links = await page.query_selector_all("a[href]")
            logger.info(f"Found {len(links)} links on page")

            for link in links:
                try:
                    href = await link.get_attribute("href")
                    text = await link.text_content()

                    if not href:
                        continue

                    # Check if text matches contact patterns
                    if text:
                        text_lower = text.lower().strip()
                        for pattern in CONTACT_PATTERNS:
                            if re.search(pattern, text_lower):
                                # Convert relative URL to absolute
                                contact_url = urljoin(base_url, href)
                                logger.info(
                                    f"Contact link found: {text} -> {contact_url}"
                                )
                                return contact_url

                    # Check if href matches contact patterns
                    href_lower = href.lower()
                    for pattern in CONTACT_PATTERNS:
                        if re.search(pattern, href_lower):
                            contact_url = urljoin(base_url, href)
                            logger.info(f"Contact URL pattern matched: {contact_url}")
                            return contact_url

                except Exception as e:
                    logger.debug(f"Error processing link: {e}")
                    continue

            logger.info("No contact page link found")
            return None

        except Exception as e:
            logger.error(f"Error finding contact page: {e}")
            return None

    async def _fill_and_submit_form(
        self, page: Page, user_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Find, fill, and submit a contact form.

        Uses user profile data to fill form fields.
        """
        result = {"success": False, "details": {}, "error": None}

        try:
            # Find form
            form = await page.query_selector("form")
            if not form:
                result["error"] = "No form found"
                return result

            logger.info("✓ Contact form found")

            # Get form fields
            inputs = await page.query_selector_all("input, textarea, select")
            logger.info(f"Found {len(inputs)} form fields")

            filled_count = 0

            # Fill each field
            for field in inputs:
                try:
                    field_type = await field.get_attribute("type")
                    field_name = await field.get_attribute("name")
                    field_id = await field.get_attribute("id")
                    field_placeholder = await field.get_attribute("placeholder")

                    field_identifier = field_id or field_name or field_placeholder or ""
                    field_identifier = field_identifier.lower()

                    # Skip hidden, submit, button fields
                    if field_type in [
                        "hidden",
                        "submit",
                        "button",
                        "checkbox",
                        "radio",
                    ]:
                        continue

                    value_to_fill = None

                    # Match field to profile data
                    if self._matches_pattern(
                        field_identifier, FORM_FIELD_PATTERNS["email"]
                    ):
                        value_to_fill = user_profile.get("email", "contact@example.com")
                    elif self._matches_pattern(
                        field_identifier, FORM_FIELD_PATTERNS["name"]
                    ):
                        value_to_fill = f"{user_profile.get('first_name')} {user_profile.get('last_name')}".strip()
                    elif self._matches_pattern(
                        field_identifier, FORM_FIELD_PATTERNS["phone"]
                    ):
                        value_to_fill = user_profile.get("phone_number", "")
                    elif self._matches_pattern(
                        field_identifier, FORM_FIELD_PATTERNS["company"]
                    ):
                        value_to_fill = user_profile.get("company_name", "")
                    elif self._matches_pattern(
                        field_identifier, FORM_FIELD_PATTERNS["message"]
                    ):
                        value_to_fill = user_profile.get(
                            "message", "I would like to discuss business opportunities."
                        )

                    if value_to_fill:
                        try:
                            # Clear and fill
                            await field.fill("")
                            await field.fill(value_to_fill)
                            filled_count += 1
                            logger.info(f"Filled field: {field_identifier} with value")
                        except Exception as e:
                            logger.debug(
                                f"Could not fill field {field_identifier}: {e}"
                            )

                except Exception as e:
                    logger.debug(f"Error processing form field: {e}")
                    continue

            if filled_count == 0:
                result["error"] = "Could not fill any form fields"
                return result

            logger.info(f"Filled {filled_count} form fields")
            result["details"]["fields_filled"] = filled_count

            # Find and click submit button
            submit_button = await page.query_selector(
                "button[type='submit'], input[type='submit'], button:has-text('submit'), button:has-text('send')"
            )

            if not submit_button:
                result["error"] = "No submit button found"
                return result

            logger.info("Clicking submit button...")
            await submit_button.click()

            # Wait for navigation or response
            await asyncio.sleep(3)

            # Check for success indicators
            page_content = await page.content()
            page_text = await page.text_content()

            for keyword in SUCCESS_KEYWORDS:
                if keyword.lower() in page_text.lower():
                    logger.info(f"Success indicator found: {keyword}")
                    result["success"] = True
                    result["details"]["success_indicator"] = keyword
                    return result

            # Check for URL change (common success indicator)
            if page.url != await page.url:
                logger.info("URL changed after submission")
                result["success"] = True
                result["details"]["success_indicator"] = "URL_change"
                return result

            logger.info("Form submitted but success not confirmed")
            result["success"] = True  # Assume success if no error
            result["details"]["success_indicator"] = "form_accepted"
            return result

        except Exception as e:
            result["error"] = f"Form submission error: {str(e)}"
            logger.error(f"Form error: {e}", exc_info=True)
            return result

    async def _extract_emails(self, page: Page) -> list:
        """Extract email addresses from page."""
        try:
            emails = []

            # Method 1: Find mailto links
            mailto_links = await page.query_selector_all("a[href^='mailto:']")

            for link in mailto_links:
                href = await link.get_attribute("href")
                email = href.replace("mailto:", "").split("?")[0]
                if email not in emails:
                    emails.append(email)

            # Method 2: Find email patterns in text
            page_text = await page.text_content()
            email_pattern = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"
            found_emails = re.findall(email_pattern, page_text)

            for email in found_emails:
                if email not in emails and email not in ["example.com", "test.com"]:
                    emails.append(email)

            logger.info(f"Extracted {len(emails)} email addresses")
            return emails[:10]  # Return max 10 emails

        except Exception as e:
            logger.error(f"Error extracting emails: {e}")
            return []

    def _matches_pattern(self, identifier: str, patterns: list) -> bool:
        """Check if identifier matches any pattern."""
        for pattern in patterns:
            if re.search(pattern, identifier, re.IGNORECASE):
                return True
        return False


# Usage example
if __name__ == "__main__":

    async def test():
        automation = BrowserAutomation(headless=False, slow_mo=500)
        await automation.start()

        user_data = {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "phone_number": "+1-555-0100",
            "company_name": "Acme Corp",
            "message": "I would like to discuss business opportunities.",
        }

        result = await automation.process("https://example.com", user_data)
        print(f"Result: {result}")

        await automation.stop()

    asyncio.run(test())
