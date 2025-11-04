"""Quick script to check submission errors for a campaign"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not found in .env")
    sys.exit(1)

# Campaign ID from command line or use the one from logs
campaign_id = sys.argv[1] if len(sys.argv) > 1 else "5f805a52-cc9b-47f8-bab4-95feb3b8b23c"

engine = create_engine(DATABASE_URL)
with engine.connect() as conn:
    # Get submissions with error messages
    query = text("""
        SELECT 
            id, url, status, success, error_message, 
            created_at, updated_at
        FROM submissions 
        WHERE campaign_id = :campaign_id
        ORDER BY created_at DESC
    """)
    
    results = conn.execute(query, {"campaign_id": campaign_id}).mappings().all()
    
    print(f"\n{'='*80}")
    print(f"Submission Errors for Campaign: {campaign_id}")
    print(f"{'='*80}\n")
    
    if not results:
        print("No submissions found for this campaign.")
    else:
        for i, sub in enumerate(results, 1):
            print(f"Submission {i}:")
            print(f"  URL: {sub.get('url')}")
            print(f"  Status: {sub.get('status')}")
            print(f"  Success: {sub.get('success')}")
            print(f"  Error: {sub.get('error_message') or 'No error message'}")
            print()

