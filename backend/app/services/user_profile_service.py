# app/services/user_profile_service.py
from typing import Dict, Any, Optional
from app.core.database import get_db
from app.models.user_profile import UserProfile


class UserProfileService:
    """Service for managing user profile data for form filling."""

    def __init__(self, db_session):
        self.db = db_session

    async def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        """Get user profile data for form filling."""
        profile = (
            self.db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
        )

        if not profile:
            # Return default profile
            return self.get_default_profile()

        return {
            # Personal Information
            "name": profile.full_name,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "phone": profile.phone,
            "company": profile.company,
            "job_title": profile.job_title,
            "website": profile.website,
            # Message Templates
            "message": profile.default_message or self._get_default_message(),
            "subject": profile.default_subject or "Business Inquiry",
            # Preferences
            "newsletter_consent": profile.newsletter_consent or False,
            "marketing_consent": profile.marketing_consent or False,
            # Additional Fields
            "budget": profile.budget_range,
            "timeline": profile.project_timeline,
            "industry": profile.industry,
            "company_size": profile.company_size,
        }

    def get_default_profile(self) -> Dict[str, Any]:
        """Get default profile for testing."""
        return {
            "name": "John Doe",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
            "phone": "555-0100",
            "company": "Example Corp",
            "job_title": "Manager",
            "website": "https://example.com",
            "message": "I am interested in learning more about your services.",
            "subject": "Business Inquiry",
            "newsletter_consent": False,
            "marketing_consent": False,
        }

    def _get_default_message(self) -> str:
        """Generate default message."""
        return """
        I am interested in learning more about your services and would 
        appreciate the opportunity to discuss how we might work together. 
        Please feel free to contact me at your earliest convenience.
        """
