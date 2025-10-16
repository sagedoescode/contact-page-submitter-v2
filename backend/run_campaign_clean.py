# run_campaign_clean.py - Run campaign with clean logging
"""
Clean way to run a campaign with minimal logs.
Shows only important information about campaign progress.
"""

import os
import sys
import logging
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

# Import logging config FIRST
from app.core.logging_config import setup_campaign_logging, setup_file_logging

# Setup clean logging (set verbose=True to see all logs)
setup_campaign_logging(verbose=False)

# Now import campaign processor
from app.workers.processors.campaign_processor import process_campaign_submissions
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def get_pending_campaign():
    """Find a campaign that needs processing."""
    try:
        DATABASE_URL = os.getenv("DATABASE_URL")
        engine = create_engine(DATABASE_URL)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        query = text(
            """
            SELECT id, user_id, name, status, total_urls
            FROM campaigns
            WHERE status IN ('PENDING', 'RUNNING')
            ORDER BY created_at DESC
            LIMIT 1
        """
        )

        result = db.execute(query).mappings().first()
        db.close()

        return result
    except Exception as e:
        logger.error(f"❌ Error finding campaign: {e}")
        return None


def run_campaign_by_id(campaign_id: str, user_id: str):
    """Run a specific campaign with clean logging."""
    print("\n" + "=" * 60)
    print("🚀 CAMPAIGN PROCESSOR - CLEAN MODE")
    print("=" * 60)
    print(f"Campaign ID: {campaign_id[:8]}...")
    print(f"User ID: {user_id[:8]}...")
    print("=" * 60 + "\n")

    # Setup file logging for this campaign
    log_file = setup_file_logging(campaign_id=campaign_id)

    try:
        # Run the campaign
        process_campaign_submissions(campaign_id, user_id)

        print("\n" + "=" * 60)
        print("✅ CAMPAIGN COMPLETED")
        print("=" * 60)
        print(f"📝 Full logs saved to: {log_file}")
        print("=" * 60 + "\n")

    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("⚠️ CAMPAIGN INTERRUPTED BY USER")
        print("=" * 60)
        print(f"📝 Partial logs saved to: {log_file}")
        print("=" * 60 + "\n")

    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ CAMPAIGN FAILED")
        print("=" * 60)
        print(f"Error: {e}")
        print(f"📝 Error logs saved to: {log_file}")
        print("=" * 60 + "\n")


def run_next_pending_campaign():
    """Find and run the next pending campaign."""
    print("\n🔍 Looking for pending campaigns...\n")

    campaign = get_pending_campaign()

    if not campaign:
        print("❌ No pending campaigns found\n")
        print("💡 Create a campaign first:")
        print("   1. Go to your web app")
        print("   2. Upload a CSV file")
        print("   3. Start a campaign")
        print("   4. Run this script again\n")
        return

    print(f"✅ Found campaign: {campaign['name']}")
    print(f"   Status: {campaign['status']}")
    print(f"   Total URLs: {campaign['total_urls']}\n")

    # Run the campaign
    run_campaign_by_id(campaign["id"], campaign["user_id"])


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Run campaign with clean logs")
    parser.add_argument("--campaign-id", help="Specific campaign ID to run")
    parser.add_argument(
        "--user-id", help="User ID (required if campaign-id is specified)"
    )
    parser.add_argument("--verbose", action="store_true", help="Show all logs")

    args = parser.parse_args()

    # Update logging if verbose
    if args.verbose:
        setup_campaign_logging(verbose=True)

    if args.campaign_id:
        if not args.user_id:
            print("❌ Error: --user-id is required when using --campaign-id\n")
            return

        run_campaign_by_id(args.campaign_id, args.user_id)
    else:
        run_next_pending_campaign()


if __name__ == "__main__":
    main()
