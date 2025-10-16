# app/workers/automation/form_filler.py - FIXED VERSION
"""Enhanced form filler with CORRECTED user data mapping."""

import asyncio
from typing import Dict, Any, List, Optional
from playwright.async_api import ElementHandle, Page
from app.workers.utils.logger import WorkerLogger
from app.workers.automation.form_detector import FormAnalysisResult


class FormFillResult:
    """Result of form filling operation."""

    def __init__(self, success: bool, fields_filled: int, errors: List[str] = None):
        self.success = success
        self.fields_filled = fields_filled
        self.errors = errors or []
        self.field_mappings = {}


class FormFiller:
    """Intelligent form filler with FIXED user data mapping."""

    def __init__(
        self, user_id: Optional[str] = None, campaign_id: Optional[str] = None
    ):
        self.user_id = user_id
        self.campaign_id = campaign_id
        self.logger = WorkerLogger(user_id=user_id, campaign_id=campaign_id)

    async def fill_form(
        self, page: Page, form_analysis: FormAnalysisResult, user_data: Dict[str, Any]
    ) -> FormFillResult:
        """
        Fill form using user data - FIXED VERSION.

        Args:
            page: The page containing the form
            form_analysis: Analysis result from form detector
            user_data: User's profile data from database
        """
        self.logger.info("Starting form fill with user data")
        self.logger.info(f"User data keys: {list(user_data.keys())}")

        try:
            # Normalize user data to ensure all expected fields exist
            normalized_data = self._normalize_user_data(user_data)
            self.logger.info(f"Normalized data: {list(normalized_data.keys())}")

            # Get all fillable fields
            fields = await self._get_fillable_fields(form_analysis.form)
            self.logger.info(f"Found {len(fields)} fillable fields")

            if not fields:
                return FormFillResult(
                    success=False, fields_filled=0, errors=["No fillable fields found"]
                )

            # Fill each field
            filled_count = 0
            errors = []
            field_mappings = {}

            for field in fields:
                try:
                    field_name = field.get("name") or field.get("id") or "unknown"
                    field_type = field.get("type", "text")
                    field_element = field.get("element")

                    if not field_element:
                        continue

                    # Get appropriate value for this field
                    value = self._map_field_to_value(
                        field_name=field_name,
                        field_type=field_type,
                        field_info=field,
                        user_data=normalized_data,
                    )

                    if value is not None:
                        self.logger.info(
                            f"Filling '{field_name}' ({field_type}) with: {str(value)[:50]}"
                        )

                        # Fill the field
                        success = await self._fill_field(
                            field_element, value, field_type
                        )

                        if success:
                            filled_count += 1
                            field_mappings[field_name] = value
                            self.logger.info(f"✓ Successfully filled '{field_name}'")
                        else:
                            errors.append(f"Failed to fill {field_name}")
                            self.logger.warning(f"✗ Failed to fill '{field_name}'")

                        # Small delay between fields
                        await asyncio.sleep(0.2)

                except Exception as e:
                    error_msg = f"Error filling field: {str(e)}"
                    errors.append(error_msg)
                    self.logger.warning(error_msg)

            # Create result
            result = FormFillResult(
                success=filled_count > 0, fields_filled=filled_count, errors=errors
            )
            result.field_mappings = field_mappings

            self.logger.info(
                f"Form fill complete: {filled_count}/{len(fields)} fields filled"
            )

            return result

        except Exception as e:
            self.logger.error(f"Form filling failed: {str(e)}")
            return FormFillResult(success=False, fields_filled=0, errors=[str(e)])

    def _normalize_user_data(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize user data to ensure all expected fields exist.
        CRITICAL FIX: Create comprehensive field mappings.
        """
        normalized = {}

        # Map all possible field name variations
        # Email field variations
        email = user_data.get("email", "")
        normalized["email"] = email
        normalized["e-mail"] = email
        normalized["mail"] = email
        normalized["emailaddress"] = email
        normalized["email_address"] = email
        normalized["your-email"] = email
        normalized["youremail"] = email

        # Name field variations
        first_name = user_data.get("first_name", "")
        last_name = user_data.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip() or "User"

        normalized["first_name"] = first_name
        normalized["firstname"] = first_name
        normalized["fname"] = first_name
        normalized["given_name"] = first_name
        normalized["last_name"] = last_name
        normalized["lastname"] = last_name
        normalized["lname"] = last_name
        normalized["surname"] = last_name
        normalized["family_name"] = last_name
        normalized["name"] = full_name
        normalized["full_name"] = full_name
        normalized["fullname"] = full_name
        normalized["your-name"] = full_name
        normalized["yourname"] = full_name

        # Phone field variations
        phone = user_data.get("phone_number", "") or user_data.get("phone", "")
        normalized["phone"] = phone
        normalized["phone_number"] = phone
        normalized["phonenumber"] = phone
        normalized["telephone"] = phone
        normalized["tel"] = phone
        normalized["mobile"] = phone
        normalized["cell"] = phone
        normalized["contact_number"] = phone
        normalized["your-phone"] = phone

        # Company field variations
        company = user_data.get("company_name", "") or user_data.get("company", "")
        normalized["company"] = company
        normalized["company_name"] = company
        normalized["companyname"] = company
        normalized["organization"] = company
        normalized["organisation"] = company
        normalized["business"] = company

        # Job title variations
        job_title = user_data.get("job_title", "") or user_data.get("title", "")
        normalized["job_title"] = job_title
        normalized["jobtitle"] = job_title
        normalized["title"] = job_title
        normalized["position"] = job_title
        normalized["role"] = job_title

        # Message field variations
        message = (
            user_data.get("message", "")
            or "I would like to discuss business opportunities."
        )
        normalized["message"] = message
        normalized["comment"] = message
        normalized["comments"] = message
        normalized["inquiry"] = message
        normalized["enquiry"] = message
        normalized["question"] = message
        normalized["details"] = message
        normalized["description"] = message
        normalized["your-message"] = message
        normalized["yourmessage"] = message

        # Subject field variations
        subject = user_data.get("subject", "") or "Business Inquiry"
        normalized["subject"] = subject
        normalized["topic"] = subject
        normalized["regarding"] = subject
        normalized["your-subject"] = subject

        # Website field variations
        website = user_data.get("website_url", "") or user_data.get("website", "")
        normalized["website"] = website
        normalized["website_url"] = website
        normalized["url"] = website
        normalized["site"] = website

        return normalized

    def _map_field_to_value(
        self,
        field_name: str,
        field_type: str,
        field_info: Dict[str, Any],
        user_data: Dict[str, Any],
    ) -> Any:
        """
        Map a field to appropriate value from user data.
        CRITICAL FIX: Improved field matching logic.
        """
        field_name_lower = field_name.lower()
        placeholder = field_info.get("placeholder", "").lower()
        field_id = field_info.get("id", "").lower()

        # Create searchable text
        searchable = f"{field_name_lower} {placeholder} {field_id}"

        # Remove special characters for matching
        clean_name = field_name_lower.replace("-", "").replace("_", "").replace(" ", "")

        self.logger.info(
            f"Mapping field: '{field_name}' (searchable: '{searchable[:50]}')"
        )

        # Try exact match first
        if field_name_lower in user_data:
            value = user_data[field_name_lower]
            if value:
                self.logger.info(f"  → Exact match found: {str(value)[:50]}")
                return value

        # Try clean name match
        if clean_name in user_data:
            value = user_data[clean_name]
            if value:
                self.logger.info(f"  → Clean name match: {str(value)[:50]}")
                return value

        # Handle checkboxes
        if field_type == "checkbox":
            # Newsletter/marketing - default to False
            if any(
                word in searchable
                for word in ["newsletter", "marketing", "promotional"]
            ):
                return False
            # Terms/privacy - default to True
            if any(
                word in searchable for word in ["terms", "privacy", "agree", "accept"]
            ):
                return True
            return False

        # Email fields
        if field_type == "email" or any(
            word in searchable for word in ["email", "e-mail", "@"]
        ):
            return user_data.get("email", "")

        # Phone fields
        if field_type == "tel" or any(
            word in searchable for word in ["phone", "tel", "mobile", "cell"]
        ):
            return user_data.get("phone", "")

        # Name fields
        if any(
            word in searchable for word in ["firstname", "first_name", "fname", "given"]
        ):
            return user_data.get("first_name", "")

        if any(
            word in searchable
            for word in ["lastname", "last_name", "lname", "surname", "family"]
        ):
            return user_data.get("last_name", "")

        if (
            any(
                word in searchable
                for word in ["fullname", "full_name", "name", "your-name"]
            )
            and "first" not in searchable
            and "last" not in searchable
        ):
            return user_data.get("name", "")

        # Company fields
        if any(
            word in searchable
            for word in ["company", "organization", "organisation", "business"]
        ):
            return user_data.get("company", "")

        # Job title
        if (
            any(word in searchable for word in ["job", "title", "position", "role"])
            and "subject" not in searchable
        ):
            return user_data.get("job_title", "")

        # Website
        if any(word in searchable for word in ["website", "url", "site"]):
            return user_data.get("website", "")

        # Subject
        if any(word in searchable for word in ["subject", "topic", "regarding"]):
            return user_data.get("subject", "")

        # Message/textarea fields
        if field_type == "textarea" or any(
            word in searchable
            for word in ["message", "comment", "inquiry", "question", "details"]
        ):
            return user_data.get("message", "")

        # Select fields - try to find safe option
        if field_type == "select":
            options = field_info.get("options", [])
            if options:
                # Look for "Other" option
                for option in options:
                    if any(
                        word in option.lower()
                        for word in ["other", "not listed", "general"]
                    ):
                        return option
                return options[0]  # First option as fallback

        self.logger.info(f"  → No value found for '{field_name}'")
        return None

    async def _get_fillable_fields(self, form: ElementHandle) -> List[Dict[str, Any]]:
        """Get all fillable fields from form."""
        fields = []

        try:
            # Get input fields
            inputs = await form.query_selector_all("input")
            for input_elem in inputs:
                try:
                    input_type = (
                        await input_elem.get_attribute("type") or "text"
                    ).lower()

                    # Skip non-fillable types
                    if input_type in [
                        "submit",
                        "button",
                        "hidden",
                        "image",
                        "reset",
                        "file",
                    ]:
                        continue

                    if not await input_elem.is_visible():
                        continue

                    field_info = {
                        "element": input_elem,
                        "type": input_type,
                        "name": await input_elem.get_attribute("name") or "",
                        "id": await input_elem.get_attribute("id") or "",
                        "placeholder": await input_elem.get_attribute("placeholder")
                        or "",
                        "required": await input_elem.get_attribute("required")
                        is not None,
                    }
                    fields.append(field_info)

                except Exception as e:
                    self.logger.warning(f"Error analyzing input: {e}")

            # Get textarea fields
            textareas = await form.query_selector_all("textarea")
            for textarea in textareas:
                try:
                    if not await textarea.is_visible():
                        continue

                    field_info = {
                        "element": textarea,
                        "type": "textarea",
                        "name": await textarea.get_attribute("name") or "",
                        "id": await textarea.get_attribute("id") or "",
                        "placeholder": await textarea.get_attribute("placeholder")
                        or "",
                        "required": await textarea.get_attribute("required")
                        is not None,
                    }
                    fields.append(field_info)

                except Exception as e:
                    self.logger.warning(f"Error analyzing textarea: {e}")

            # Get select fields
            selects = await form.query_selector_all("select")
            for select in selects:
                try:
                    if not await select.is_visible():
                        continue

                    # Get options
                    options = []
                    option_elements = await select.query_selector_all("option")
                    for option in option_elements:
                        option_value = await option.get_attribute("value")
                        option_text = await option.inner_text()
                        final_value = option_value if option_value else option_text
                        if final_value and final_value.strip():
                            options.append(final_value.strip())

                    field_info = {
                        "element": select,
                        "type": "select",
                        "name": await select.get_attribute("name") or "",
                        "id": await select.get_attribute("id") or "",
                        "options": options,
                        "required": await select.get_attribute("required") is not None,
                    }
                    fields.append(field_info)

                except Exception as e:
                    self.logger.warning(f"Error analyzing select: {e}")

        except Exception as e:
            self.logger.error(f"Error getting fillable fields: {e}")

        return fields

    async def _fill_field(
        self, element: ElementHandle, value: Any, field_type: str
    ) -> bool:
        """Fill a field with appropriate value."""
        try:
            if field_type == "checkbox":
                is_checked = await element.is_checked()
                target_state = bool(value)
                if target_state != is_checked:
                    await element.click()
                return True

            elif field_type == "select":
                try:
                    await element.select_option(str(value))
                    return True
                except:
                    # Try clicking and selecting
                    await element.click()
                    await asyncio.sleep(0.2)
                    options = await element.query_selector_all("option")
                    for option in options:
                        option_text = await option.inner_text()
                        if str(value) in option_text:
                            await option.click()
                            return True
                    return False

            else:
                # Text input
                await element.focus()
                await asyncio.sleep(0.1)

                # Clear and fill
                await element.fill("")
                await element.type(str(value), delay=30)

                # Trigger events
                await element.dispatch_event("input")
                await element.dispatch_event("change")
                await element.dispatch_event("blur")

                return True

        except Exception as e:
            self.logger.warning(f"Error filling field: {e}")
            return False
