import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from passlib.context import CryptContext
import uuid
from datetime import datetime

# Your database URL
DATABASE_URL = "postgresql://neondb_owner:npg_TIN40HCxdqBU@ep-long-glitter-aekty8cj-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require"

# User details
email = "testlogin@example.com"
password = "TestLogin123!"
first_name = "Test"
last_name = "Login"

# Hash the password
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
hashed_password = pwd_context.hash(password)

print(f"Creating user: {email}")
print(f"Password: {password}")
print(f"Hash preview: {hashed_password[:20]}...")

# Connect and create user
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Delete if exists
    conn.execute(text("DELETE FROM users WHERE email = :email"), {"email": email})
    conn.commit()

    # Create new user
    user_id = str(uuid.uuid4())
    result = conn.execute(
        text(
            """
        INSERT INTO users (
            id, email, hashed_password, first_name, last_name,
            role, is_active, created_at, subscription_status
        ) VALUES (
            :id, :email, :password, :first_name, :last_name,
            'user', true, :created_at, 'free'
        )
        RETURNING id
    """
        ),
        {
            "id": user_id,
            "email": email,
            "password": hashed_password,
            "first_name": first_name,
            "last_name": last_name,
            "created_at": datetime.utcnow(),
        },
    )
    conn.commit()

    print(f"✅ User created with ID: {user_id}")

    # Verify it was created
    result = conn.execute(
        text("SELECT email, is_active FROM users WHERE email = :email"),
        {"email": email},
    ).fetchone()

    if result:
        print(f"✅ Verified: User exists in database")
        print(f"   Email: {result[0]}")
        print(f"   Active: {result[1]}")

print(f"\n📝 Test login with:")
print(f"   Email: {email}")
print(f"   Password: {password}")
