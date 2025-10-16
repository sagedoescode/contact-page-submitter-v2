# app/services/submission_service.py - FIXED VERSION
"""Submission service for managing form submissions."""

import uuid
import logging
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class SubmissionService:
    """Service for managing submissions."""

    # Valid status values
    VALID_STATUSES = {"pending", "processing", "completed", "failed", "retry"}

    def __init__(self, db: Session):
        self.db = db

    def bulk_create_submissions(
        self, user_id: uuid.UUID, campaign_id: uuid.UUID, urls: List[str]
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Bulk create submissions from a list of URLs.

        FIXED: Status field is now optional and defaults to 'pending'
        """
        submissions = []
        errors = []

        logger.info(f"Creating submissions for {len(urls)} URLs")

        for idx, url in enumerate(urls, 1):
            try:
                # Clean URL
                url = url.strip()
                if not url:
                    errors.append(f"Row {idx}: Empty URL")
                    continue

                # Create submission record
                submission_id = str(uuid.uuid4())
                now = datetime.utcnow()

                # Default status is always 'pending' - no validation needed from CSV
                status = "pending"

                insert_query = text(
                    """
                    INSERT INTO submissions (
                        id, campaign_id, user_id, url, status,
                        created_at, updated_at
                    ) VALUES (
                        :id, :campaign_id, :user_id, :url, :status,
                        :created_at, :updated_at
                    )
                """
                )

                self.db.execute(
                    insert_query,
                    {
                        "id": submission_id,
                        "campaign_id": str(campaign_id),
                        "user_id": str(user_id),
                        "url": url,
                        "status": status,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

                submissions.append(
                    {
                        "id": submission_id,
                        "url": url,
                        "status": status,
                        "created_at": now,
                    }
                )

            except SQLAlchemyError as e:
                error_msg = f"Row {idx}: Database error - {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                continue
            except Exception as e:
                error_msg = f"Row {idx}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                continue

        logger.info(f"Bulk created {len(submissions)} submissions")
        if errors:
            logger.warning(f"Encountered {len(errors)} errors during bulk creation")

        return submissions, errors

    def get_submission(
        self, submission_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> Optional[Dict[str, Any]]:
        """Get a submission by ID."""
        try:
            query = text(
                """
                SELECT * FROM submissions 
                WHERE id = :submission_id
            """
            )

            params = {"submission_id": str(submission_id)}

            if user_id:
                query = text(
                    """
                    SELECT * FROM submissions 
                    WHERE id = :submission_id AND user_id = :user_id
                """
                )
                params["user_id"] = str(user_id)

            result = self.db.execute(query, params).mappings().first()
            return dict(result) if result else None

        except Exception as e:
            logger.error(f"Error getting submission {submission_id}: {e}")
            return None

    def update_submission_status(
        self,
        submission_id: uuid.UUID,
        status: str,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update submission status."""
        try:
            # Validate status
            if status not in self.VALID_STATUSES:
                logger.error(f"Invalid status: {status}")
                return False

            query = text(
                """
                UPDATE submissions 
                SET status = :status,
                    error_message = :error_message,
                    updated_at = :updated_at
                WHERE id = :submission_id
            """
            )

            self.db.execute(
                query,
                {
                    "submission_id": str(submission_id),
                    "status": status,
                    "error_message": error_message,
                    "updated_at": datetime.utcnow(),
                },
            )
            self.db.commit()

            logger.info(f"Updated submission {submission_id} to status: {status}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating submission status: {e}")
            return False

    def get_campaign_submissions(
        self,
        campaign_id: uuid.UUID,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get submissions for a campaign."""
        try:
            base_query = """
                SELECT * FROM submissions 
                WHERE campaign_id = :campaign_id
            """

            params: Dict[str, Any] = {"campaign_id": str(campaign_id)}

            if status:
                base_query += " AND status = :status"
                params["status"] = status

            base_query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
            params["limit"] = limit
            params["offset"] = offset

            result = self.db.execute(text(base_query), params).mappings().all()
            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Error getting campaign submissions: {e}")
            return []

    def delete_submission(
        self, submission_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> bool:
        """Delete a submission."""
        try:
            query = text("DELETE FROM submissions WHERE id = :submission_id")
            params = {"submission_id": str(submission_id)}

            if user_id:
                query = text(
                    "DELETE FROM submissions WHERE id = :submission_id AND user_id = :user_id"
                )
                params["user_id"] = str(user_id)

            result = self.db.execute(query, params)
            self.db.commit()

            if result.rowcount > 0:
                logger.info(f"Deleted submission {submission_id}")
                return True
            else:
                logger.warning(f"Submission {submission_id} not found or unauthorized")
                return False

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting submission: {e}")
            return False
