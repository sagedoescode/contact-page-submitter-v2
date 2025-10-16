# verify_password.py
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from passlib.context import CryptContext

DATABASE_URL = "postgresql://neondb_owner:npg_TIN40HCxdqBU@ep-long-glitter-aekty8cj-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require"

email = "testlogin@example.com"  # Change this
password = "TestLogin123!"  # Change this

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(
        text("SELECT hashed_password, is_active FROM users WHERE email = :email"),
        {"email": email},
    ).fetchone()

    if not result:
        print(f"❌ User {email} not found")
    else:
        stored_hash = result[0]
        is_active = result[1]

        print(f"User: {email}")
        print(f"Active: {is_active}")
        print(f"Hash starts with: {stored_hash[:20]}...")

        # Verify password
        is_valid = pwd_context.verify(password, stored_hash)
        print(f"Password '{password}' is valid: {is_valid}")
