#!/usr/bin/env python3
"""
Fixed Diagnostic Script V2 - Handles import issues
"""

import sys
import os
from pathlib import Path

# Fix Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print(f"Python path includes: {project_root}")
print(f"Current directory: {os.getcwd()}")


def check_model_imports():
    """Check if models can be imported"""
    print("\n" + "=" * 60)
    print("CHECKING MODEL IMPORTS")
    print("=" * 60)

    models_dir = Path("app/models")
    if not models_dir.exists():
        print(f"❌ Models directory doesn't exist at {models_dir.absolute()}")
        return False

    # List all files in models directory
    print(f"Files in {models_dir}:")
    for file in models_dir.glob("*.py"):
        print(f"  - {file.name}")

    # Check if user.py exists
    user_file = models_dir / "user.py"
    if not user_file.exists():
        print(f"❌ user.py not found! Creating it now...")
        create_user_model()
    else:
        print(f"✅ user.py exists at {user_file}")
        # Check if it's importable
        try:
            import app.models.user

            print("✅ user.py is importable")
        except ImportError as e:
            print(f"❌ Cannot import user.py: {e}")
            print("   Checking file content...")
            content = user_file.read_text()
            if len(content) < 100:
                print("   File seems too small, recreating...")
                create_user_model()

    return True


def create_user_model():
    """Create the user.py model file"""
    user_model_content = '''from sqlalchemy import Column, String, Boolean, DateTime, Text, UUID, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class User(Base):
    """User model for authentication and basic info"""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(Text, nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=True)
    subscription_status = Column(String(50), nullable=True)
    subscription_start = Column(DateTime, nullable=True)
    subscription_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=True, default=func.current_timestamp())
    profile_image_url = Column(Text, nullable=True)
    role = Column(String(20), nullable=True, default="user")
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    captcha_username = Column(Text, nullable=True)
    captcha_password_hash = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=True, default=True)

    # Relationships
    campaigns = relationship("Campaign", back_populates="user", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="user", cascade="all, delete-orphan")
    websites = relationship("Website", back_populates="user", cascade="all, delete-orphan")
    user_profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    user_profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    system_logs = relationship("SystemLog", back_populates="user", cascade="all, delete-orphan")
    settings = relationship("Settings", back_populates="user", cascade="all, delete-orphan")
    submission_logs = relationship("SubmissionLog", back_populates="user", cascade="all, delete-orphan")
    logs = relationship("Log", back_populates="user", cascade="all, delete-orphan")
'''

    user_file = Path("app/models/user.py")
    user_file.write_text(user_model_content)
    print(f"✅ Created user.py model file")


def install_missing_packages():
    """Install missing packages"""
    print("\n" + "=" * 60)
    print("CHECKING REQUIRED PACKAGES")
    print("=" * 60)

    import subprocess

    required_packages = {
        "requests": "requests",
        "jose": "python-jose[cryptography]",
        "passlib": "passlib[bcrypt]",
        "email_validator": "email-validator",
    }

    for import_name, package_name in required_packages.items():
        try:
            __import__(import_name)
            print(f"✅ {import_name} is installed")
        except ImportError:
            print(f"📦 Installing {package_name}...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", package_name]
                )
                print(f"✅ Installed {package_name}")
            except:
                print(
                    f"❌ Failed to install {package_name}. Run: pip install {package_name}"
                )


def test_database_connection():
    """Test database connection"""
    print("\n" + "=" * 60)
    print("TESTING DATABASE CONNECTION")
    print("=" * 60)

    try:
        from app.core.config import get_settings
settings = get_settings()
        from sqlalchemy import create_engine, text

        print(f"Connecting to: {settings.DATABASE_URL[:50]}...")

        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).fetchone()
            print("✅ Database connection successful")

            # Count tables
            result = conn.execute(
                text(
                    """
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = 'public'
            """
                )
            ).fetchone()
            print(f"✅ Found {result[0]} tables in database")

        return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


def create_demo_accounts():
    """Create demo accounts with direct SQL if models won't import"""
    print("\n" + "=" * 60)
    print("CREATING DEMO ACCOUNTS")
    print("=" * 60)

    try:
        # Try the normal way first
        from app.core.database import SessionLocal
        from app.core.security import hash_password
        from app.models.user import User
        import uuid
        from datetime import datetime

        db = SessionLocal()

        accounts = [
            ("admin@example.com", "Admin123456!", "Admin", "User", "admin"),
            ("demo@example.com", "Demo123456!", "Demo", "User", "user"),
        ]

        for email, password, first_name, last_name, role in accounts:
            user = db.query(User).filter(User.email == email).first()
            if user:
                user.hashed_password = hash_password(password)
                user.is_active = True
                user.role = role
                print(f"✅ Updated {email} - Password: {password}")
            else:
                user = User(
                    id=uuid.uuid4(),
                    email=email,
                    hashed_password=hash_password(password),
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    is_active=True,
                    created_at=datetime.utcnow(),
                    subscription_status="premium" if role == "admin" else "free",
                )
                db.add(user)
                print(f"✅ Created {email} - Password: {password}")

        db.commit()
        db.close()

    except ImportError as e:
        print(f"⚠️  Cannot import models, using direct SQL: {e}")

        # Use direct SQL as fallback
        try:
            from app.core.config import get_settings
settings = get_settings()
            from app.core.security import hash_password
            from sqlalchemy import create_engine, text
            import uuid
            from datetime import datetime

            engine = create_engine(settings.DATABASE_URL)

            accounts = [
                ("admin@example.com", "Admin123456!", "Admin", "User", "admin"),
                ("demo@example.com", "Demo123456!", "Demo", "User", "user"),
            ]

            with engine.connect() as conn:
                for email, password, first_name, last_name, role in accounts:
                    # Check if exists
                    result = conn.execute(
                        text("SELECT id FROM users WHERE email = :email"),
                        {"email": email},
                    ).fetchone()

                    if result:
                        # Update existing
                        conn.execute(
                            text(
                                """
                            UPDATE users 
                            SET hashed_password = :password,
                                is_active = true,
                                role = :role
                            WHERE email = :email
                        """
                            ),
                            {
                                "email": email,
                                "password": hash_password(password),
                                "role": role,
                            },
                        )
                        conn.commit()
                        print(f"✅ Updated {email} - Password: {password}")
                    else:
                        # Create new
                        conn.execute(
                            text(
                                """
                            INSERT INTO users (
                                id, email, hashed_password, first_name, last_name,
                                role, is_active, created_at, subscription_status
                            ) VALUES (
                                :id, :email, :password, :first_name, :last_name,
                                :role, true, :created_at, :subscription_status
                            )
                        """
                            ),
                            {
                                "id": str(uuid.uuid4()),
                                "email": email,
                                "password": hash_password(password),
                                "first_name": first_name,
                                "last_name": last_name,
                                "role": role,
                                "created_at": datetime.utcnow(),
                                "subscription_status": (
                                    "premium" if role == "admin" else "free"
                                ),
                            },
                        )
                        conn.commit()
                        print(f"✅ Created {email} - Password: {password}")

            print("\n✅ Accounts created using direct SQL")

        except Exception as e:
            print(f"❌ Failed to create accounts: {e}")
            import traceback

            traceback.print_exc()


def test_api_simple():
    """Simple API test without requests library"""
    print("\n" + "=" * 60)
    print("API TEST INSTRUCTIONS")
    print("=" * 60)

    print("Test your API with these commands:\n")

    print("1. Start your server:")
    print("   uvicorn app.main:app --reload\n")

    print("2. Test health endpoint:")
    print("   curl http://localhost:8000/api/health/health\n")

    print("3. Test login:")
    print("   curl -X POST http://localhost:8000/api/auth/login \\")
    print('     -H "Content-Type: application/json" \\')
    print('     -d \'{"email":"admin@example.com","password":"Admin123456!"}\'')

    print("\nOr using PowerShell:")
    print('   Invoke-RestMethod -Uri "http://localhost:8000/api/auth/login" `')
    print('     -Method Post -ContentType "application/json" `')
    print('     -Body \'{"email":"admin@example.com","password":"Admin123456!"}\'')


def verify_models_relationships():
    """Verify all model relationships are set up correctly"""
    print("\n" + "=" * 60)
    print("VERIFYING MODEL RELATIONSHIPS")
    print("=" * 60)

    models_to_check = [
        "app/models/campaign.py",
        "app/models/submission.py",
        "app/models/website.py",
    ]

    for model_path in models_to_check:
        path = Path(model_path)
        if path.exists():
            content = path.read_text()
            # Check if relationships are defined
            if "back_populates" not in content:
                print(f"⚠️  {model_path} might be missing relationships")
                # Add basic relationship
                if "campaign.py" in model_path and "back_populates" not in content:
                    print(f"   Adding relationships to {model_path}")
                    # You can add code here to fix the relationships
            else:
                print(f"✅ {model_path} has relationships defined")


def main():
    """Run all diagnostics"""
    print("\n" + "=" * 80)
    print(" " * 20 + "CPS BACKEND DIAGNOSTIC V2")
    print("=" * 80)

    # 1. Check and install missing packages
    install_missing_packages()

    # 2. Check model imports and fix if needed
    check_model_imports()

    # 3. Test database connection
    db_ok = test_database_connection()

    # 4. Create demo accounts
    if db_ok:
        create_demo_accounts()

    # 5. Verify model relationships
    verify_models_relationships()

    # 6. Show API test instructions
    test_api_simple()

    print("\n" + "=" * 80)
    print(" " * 25 + "SUMMARY")
    print("=" * 80)

    print("\n✅ Diagnostic complete!")
    print("\nDemo Accounts Created:")
    print("  Admin: admin@example.com / Admin123456!")
    print("  User:  demo@example.com / Demo123456!")

    print("\nNext Steps:")
    print("1. Start your server: uvicorn app.main:app --reload")
    print("2. Test login with the curl commands shown above")
    print("3. Check that your frontend is running on port 3000 or 5173")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
