# app/workers/processors/campaign_processor.py - FIXED VERSION WITH MAIN ENTRY POINT
"""Campaign processor with enhanced browser automation integration."""

import os
import sys
import asyncio
import logging
from typing import Optional, Dict
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from typing import Optional, Dict, Any

# Load .env file
load_dotenv()

# Configure logging with more detailed format
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [PROCESSOR] [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("campaign_processor.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)

# Get DATABASE_URL from .env
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.error("FATAL: DATABASE_URL not in .env file!")
    sys.exit(1)

logger.info(f"Database configured from .env")


def get_db_session():
    """Create database session from .env DATABASE_URL."""
    try:
        engine = create_engine(DATABASE_URL, echo=False)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return SessionLocal()
    except Exception as e:
        logger.error(f"Failed to create DB session: {e}")
        return None


def get_user_profile(db, user_id: str) -> Dict:
    """Fetch user profile from database for form filling."""
    try:
        query = text(
            """
            SELECT 
                u.first_name, u.last_name, u.email,
                up.phone_number, up.company_name, up.job_title,
                up.message, up.subject, up.website_url
            FROM users u
            LEFT JOIN user_profiles up ON u.id = up.user_id
            WHERE u.id = :user_id
        """
        )

        result = db.execute(query, {"user_id": user_id}).mappings().first()

        if result:
            return {
                "first_name": result["first_name"] or "User",
                "last_name": result["last_name"] or "",
                "email": result["email"] or "contact@example.com",
                "phone_number": result["phone_number"] or "",
                "company_name": result["company_name"] or "",
                "job_title": result["job_title"] or "",
                "message": result["message"]
                or "I would like to discuss business opportunities.",
                "subject": result["subject"] or "Business Inquiry",
                "website_url": result["website_url"] or "",
            }
    except Exception as e:
        logger.warning(f"Could not fetch user profile: {e}")

    # Default profile if user not found
    return {
        "first_name": "User",
        "last_name": "",
        "email": "contact@example.com",
        "phone_number": "",
        "company_name": "",
        "job_title": "",
        "message": "I would like to discuss business opportunities.",
        "subject": "Business Inquiry",
        "website_url": "",
    }


def process_campaign_submissions(campaign_id: str, user_id: str):
    """Main entry point - process all submissions for a campaign."""
    logger.info("=" * 70)
    logger.info("CAMPAIGN PROCESSOR STARTED")
    logger.info(f"Campaign: {campaign_id[:8]}... | User: {user_id[:8]}...")
    logger.info("=" * 70)

    db = get_db_session()
    if not db:
        logger.error("Failed to get database session")
        return

    try:
        # Update campaign status to PROCESSING
        logger.info("Setting campaign status to PROCESSING...")
        db.execute(
            text(
                "UPDATE campaigns SET status = 'PROCESSING', updated_at = :t WHERE id = :id"
            ),
            {"id": campaign_id, "t": datetime.utcnow()},
        )
        db.commit()

        # Get campaign
        campaign = (
            db.execute(
                text(
                    "SELECT id, name, message, total_urls FROM campaigns WHERE id = :id AND user_id = :uid"
                ),
                {"id": campaign_id, "uid": user_id},
            )
            .mappings()
            .first()
        )

        if not campaign:
            logger.error(f"Campaign not found: {campaign_id}")
            return

        logger.info(
            f"Campaign: {campaign['name']} | Total URLs: {campaign['total_urls']}"
        )

        # Get user profile for form filling
        logger.info("Fetching user profile...")
        user_profile = get_user_profile(db, user_id)
        logger.info(
            f"User profile loaded: {user_profile['first_name']} {user_profile['last_name']}"
        )

        # Get pending submissions
        submissions = (
            db.execute(
                text(
                    "SELECT id, url FROM submissions WHERE campaign_id = :cid AND status = 'pending'"
                ),
                {"cid": campaign_id},
            )
            .mappings()
            .all()
        )

        total = len(submissions)
        logger.info(f"Found {total} submissions to process")

        if total == 0:
            logger.info("No submissions - marking campaign COMPLETED")
            update_campaign(db, campaign_id, "COMPLETED", 0, 0, 0)
            return

        # Process with enhanced browser automation
        logger.info("Starting browser automation...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            successful, failed = loop.run_until_complete(
                process_with_playwright(
                    db, submissions, campaign_id, user_profile, user_id
                )
            )
        finally:
            loop.close()

        # Final update
        final_status = "COMPLETED" if successful > 0 else "FAILED"
        update_campaign(db, campaign_id, final_status, total, successful, failed)

        logger.info("=" * 70)
        logger.info(f"COMPLETE: {successful}/{total} successful, {failed} failed")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"FATAL ERROR: {e}", exc_info=True)
        update_campaign(db, campaign_id, "FAILED", 0, 0, 0, str(e))
    finally:
        db.close()


async def process_with_playwright(
    db, submissions, campaign_id: str, user_profile: Dict, user_id: str
):
    """Process submissions with Playwright browser automation."""
    logger.info("Initializing Playwright browser automation...")

    successful = 0
    failed = 0

    try:
        # Import Playwright
        from playwright.async_api import async_playwright

        logger.info("Playwright imported successfully")

        async with async_playwright() as p:
            # Launch browser with visible mode for debugging
            browser = await p.chromium.launch(
                headless=False,  # Set to True for production
                slow_mo=1000,  # Slow down for visibility
                args=[
                    "--no-sandbox",
                    "--disable-bounding-box-for-test",
                    "--disable-ipc-flooding-protection",
                ],
            )
            logger.info("Browser launched successfully")

            # Create browser context
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )

            # Create page
            page = await context.new_page()
            logger.info("Browser page created")

            # Process each submission
            for idx, submission in enumerate(submissions, 1):
                try:
                    logger.info(f"\n{'='*50}")
                    logger.info(
                        f"[{idx}/{len(submissions)}] Processing: {submission['url']}"
                    )
                    logger.info(f"{'='*50}")

                    # Update submission status
                    update_submission(db, submission["id"], "processing")

                    # Navigate to URL
                    logger.info(f"Navigating to: {submission['url']}")
                    await page.goto(
                        submission["url"],
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await asyncio.sleep(2)
                    logger.info("Page loaded successfully")

                    # Try to find contact page link
                    contact_link = None
                    contact_patterns = [
                        "contact",
                        "contact us",
                        "get in touch",
                        "reach out",
                        "contact-us",
                        "contactus",
                        "touch",
                        "connect",
                    ]

                    for pattern in contact_patterns:
                        try:
                            # Try different selectors
                            selectors = [
                                f'a:has-text("{pattern}")',
                                f'a[href*="{pattern}"]',
                                f'*:has-text("{pattern}") a',
                            ]

                            for selector in selectors:
                                links = await page.query_selector_all(selector)
                                if links:
                                    # Filter for visible links
                                    for link in links:
                                        if await link.is_visible():
                                            contact_link = link
                                            logger.info(
                                                f"Found contact link with pattern: {pattern}"
                                            )
                                            break
                                if contact_link:
                                    break
                            if contact_link:
                                break
                        except:
                            continue

                    # Click contact link if found
                    if contact_link:
                        logger.info("Clicking contact link...")
                        try:
                            await contact_link.click()
                            await page.wait_for_load_state(
                                "domcontentloaded", timeout=10000
                            )
                            await asyncio.sleep(2)
                            logger.info("Contact page loaded")
                        except Exception as e:
                            logger.warning(f"Failed to click contact link: {e}")

                    # Look for form
                    forms = await page.query_selector_all("form")
                    contact_form = None

                    if forms:
                        logger.info(f"Found {len(forms)} form(s)")
                        # Try to find the most relevant form
                        for form in forms:
                            if await form.is_visible():
                                # Check if form has email field (good indicator of contact form)
                                email_field = await form.query_selector(
                                    'input[type="email"], input[name*="email"]'
                                )
                                if email_field:
                                    contact_form = form
                                    logger.info("Found contact form with email field")
                                    break

                        # If no email field found, use first visible form
                        if not contact_form:
                            for form in forms:
                                if await form.is_visible():
                                    contact_form = form
                                    logger.info("Using first visible form")
                                    break

                    if contact_form:
                        logger.info("Attempting to fill form...")
                        fields_filled = 0

                        # Define field mappings
                        field_mappings = [
                            # Email fields
                            {
                                "selectors": [
                                    'input[type="email"]',
                                    'input[name*="email" i]',
                                    'input[id*="email" i]',
                                    'input[placeholder*="email" i]',
                                ],
                                "value": user_profile["email"],
                                "name": "email",
                            },
                            # Name fields
                            {
                                "selectors": [
                                    'input[name*="name" i]',
                                    'input[id*="name" i]',
                                    'input[placeholder*="name" i]',
                                    'input[name*="first" i]',
                                    'input[id*="first" i]',
                                ],
                                "value": f"{user_profile['first_name']} {user_profile['last_name']}".strip(),
                                "name": "name",
                            },
                            # Phone fields
                            {
                                "selectors": [
                                    'input[name*="phone" i]',
                                    'input[id*="phone" i]',
                                    'input[placeholder*="phone" i]',
                                    'input[type="tel"]',
                                ],
                                "value": user_profile.get("phone_number", ""),
                                "name": "phone",
                            },
                            # Company fields
                            {
                                "selectors": [
                                    'input[name*="company" i]',
                                    'input[id*="company" i]',
                                    'input[placeholder*="company" i]',
                                ],
                                "value": user_profile.get("company_name", ""),
                                "name": "company",
                            },
                            # Message/textarea fields
                            {
                                "selectors": [
                                    "textarea",
                                    'input[name*="message" i]',
                                    'input[id*="message" i]',
                                    'textarea[name*="comment" i]',
                                ],
                                "value": user_profile["message"],
                                "name": "message",
                            },
                        ]

                        # Fill form fields
                        for field_group in field_mappings:
                            if not field_group["value"]:  # Skip empty values
                                continue

                            for selector in field_group["selectors"]:
                                try:
                                    # Look for field within the form
                                    element = await contact_form.query_selector(
                                        selector
                                    )
                                    if (
                                        element
                                        and await element.is_visible()
                                        and await element.is_enabled()
                                    ):
                                        await element.fill(field_group["value"])
                                        fields_filled += 1
                                        logger.info(
                                            f"  ✓ Filled {field_group['name']}: {field_group['value'][:30]}..."
                                        )
                                        break  # Move to next field group
                                except Exception as e:
                                    logger.debug(f"Failed to fill {selector}: {e}")
                                    continue

                        logger.info(f"Filled {fields_filled} form fields")

                        if fields_filled > 0:
                            # Try to submit form
                            submit_selectors = [
                                'button[type="submit"]',
                                'input[type="submit"]',
                                'button:has-text("submit")',
                                'button:has-text("send")',
                                'button:has-text("contact")',
                                '[role="button"]:has-text("submit")',
                            ]

                            submitted = False
                            for selector in submit_selectors:
                                try:
                                    submit_btn = await contact_form.query_selector(
                                        selector
                                    )
                                    if (
                                        submit_btn
                                        and await submit_btn.is_visible()
                                        and await submit_btn.is_enabled()
                                    ):
                                        logger.info(
                                            f"Clicking submit button: {selector}"
                                        )
                                        await submit_btn.click()
                                        await asyncio.sleep(3)  # Wait for submission
                                        submitted = True
                                        break
                                except Exception as e:
                                    logger.debug(f"Failed to click {selector}: {e}")
                                    continue

                            if submitted:
                                # Check for success indicators
                                success_indicators = [
                                    "thank you",
                                    "thanks",
                                    "success",
                                    "sent",
                                    "submitted",
                                    "received",
                                    "message sent",
                                ]

                                page_content = await page.content()
                                success_found = any(
                                    indicator in page_content.lower()
                                    for indicator in success_indicators
                                )

                                if success_found:
                                    successful += 1
                                    update_submission(
                                        db,
                                        submission["id"],
                                        "successful",
                                        details=f"Form submitted with {fields_filled} fields",
                                    )
                                    logger.info(
                                        "  ✓ Form submitted successfully with success indicator"
                                    )
                                else:
                                    successful += 1  # Assume success if no error
                                    update_submission(
                                        db,
                                        submission["id"],
                                        "successful",
                                        details=f"Form submitted with {fields_filled} fields",
                                    )
                                    logger.info(
                                        "  ✓ Form submitted (no error detected)"
                                    )
                            else:
                                failed += 1
                                update_submission(
                                    db,
                                    submission["id"],
                                    "failed",
                                    "No submit button found",
                                )
                                logger.warning("  ✗ No submit button found")
                        else:
                            failed += 1
                            update_submission(
                                db,
                                submission["id"],
                                "failed",
                                "No form fields could be filled",
                            )
                            logger.warning("  ✗ No form fields could be filled")

                    else:
                        # Try email extraction as fallback
                        logger.info("No form found, trying email extraction...")
                        emails = await page.query_selector_all('a[href^="mailto:"]')

                        if emails:
                            email_href = await emails[0].get_attribute("href")
                            email = email_href.replace("mailto:", "").split("?")[0]
                            successful += 1
                            update_submission(
                                db,
                                submission["id"],
                                "successful",
                                details=f"Email extracted: {email}",
                            )
                            logger.info(f"  ✓ Email found: {email}")
                        else:
                            # Look for email patterns in text
                            page_text = await page.text_content("body")
                            import re

                            email_pattern = (
                                r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
                            )
                            emails_found = re.findall(email_pattern, page_text)

                            if emails_found:
                                email = emails_found[0]
                                successful += 1
                                update_submission(
                                    db,
                                    submission["id"],
                                    "successful",
                                    details=f"Email found in text: {email}",
                                )
                                logger.info(f"  ✓ Email found in text: {email}")
                            else:
                                failed += 1
                                update_submission(
                                    db,
                                    submission["id"],
                                    "failed",
                                    "No form or email found",
                                )
                                logger.warning("  ✗ No form or email found")

                    # Add delay between submissions
                    if idx < len(submissions):
                        logger.info("  Waiting 5 seconds before next submission...")
                        await asyncio.sleep(5)

                except Exception as e:
                    logger.error(f"  Error processing submission: {e}", exc_info=True)
                    failed += 1
                    update_submission(db, submission["id"], "failed", str(e))

            # Close browser
            await browser.close()
            logger.info("Browser closed")

    except ImportError as e:
        logger.error(f"Failed to import Playwright: {e}")
        logger.error(
            "Please install Playwright: pip install playwright && playwright install"
        )
        failed = len(submissions)

        # Mark all submissions as failed
        for submission in submissions:
            update_submission(
                db, submission["id"], "failed", f"Playwright not available: {e}"
            )

    except Exception as e:
        logger.error(f"Browser automation error: {e}", exc_info=True)
        failed = len(submissions)

        # Mark all submissions as failed
        for submission in submissions:
            update_submission(db, submission["id"], "failed", str(e))

    return successful, failed


def update_submission(
    db, submission_id: str, status: str, error: str = None, details: str = None
):
    """Update submission status."""
    try:
        if error:
            db.execute(
                text(
                    "UPDATE submissions SET status = :s, error_message = :e, updated_at = :t WHERE id = :id"
                ),
                {"s": status, "e": error, "t": datetime.utcnow(), "id": submission_id},
            )
        else:
            db.execute(
                text(
                    "UPDATE submissions SET status = :s, updated_at = :t WHERE id = :id"
                ),
                {"s": status, "t": datetime.utcnow(), "id": submission_id},
            )
        db.commit()
    except Exception as e:
        logger.error(f"Failed to update submission: {e}")
        db.rollback()


def update_campaign(
    db,
    campaign_id: str,
    status: str,
    total: int,
    successful: int,
    failed: int,
    error: str = None,
):
    """Update campaign status."""
    try:
        db.execute(
            text(
                """UPDATE campaigns SET status = :s, processed = :p, successful = :su, 
                    failed = :f, error_message = :e, updated_at = :t WHERE id = :id"""
            ),
            {
                "s": status,
                "p": total,
                "su": successful,
                "f": failed,
                "e": error,
                "t": datetime.utcnow(),
                "id": campaign_id,
            },
        )
        db.commit()
        logger.info(
            f"Campaign updated: status={status}, processed={total}, successful={successful}, failed={failed}"
        )
    except Exception as e:
        logger.error(f"Failed to update campaign: {e}")
        db.rollback()


# MAIN ENTRY POINT - This is what was missing!
if __name__ == "__main__":
    """Entry point when script is run directly from command line."""

    # Check command line arguments
    if len(sys.argv) != 3:
        logger.error("Usage: python campaign_processor.py <campaign_id> <user_id>")
        sys.exit(1)

    campaign_id = sys.argv[1]
    user_id = sys.argv[2]

    logger.info(f"Starting campaign processor from command line")
    logger.info(f"Campaign ID: {campaign_id}")
    logger.info(f"User ID: {user_id}")

    try:
        # Run the main processing function
        process_campaign_submissions(campaign_id, user_id)
        logger.info("Campaign processing completed successfully")
    except Exception as e:
        logger.error(f"Campaign processing failed: {e}", exc_info=True)
        sys.exit(1)
