#!/usr/bin/env python3
"""
Setup authentication for analytics dashboard.

Creates a hashed password and updates .env file.

Usage:
    python scripts/setup_analytics_auth.py
"""

import sys
import secrets
from pathlib import Path

import bcrypt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

def setup_auth():
    """Setup authentication credentials."""
    
    print("🔐 Analytics Dashboard Authentication Setup")
    print("=" * 50)
    
    # Get username
    username = input("\n👤 Enter admin username (default: admin): ").strip()
    if not username:
        username = "admin"
    
    # Get password
    password = input("🔑 Enter admin password: ").strip()
    if not password:
        print("❌ Password cannot be empty")
        sys.exit(1)
    
    # Confirm password
    password_confirm = input("🔑 Confirm password: ").strip()
    if password != password_confirm:
        print("❌ Passwords do not match")
        sys.exit(1)
    
    # Generate password hash
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Generate secret key for JWT
    secret_key = secrets.token_urlsafe(32)
    
    # Update .env file
    env_content = ""
    if ENV_FILE.exists():
        env_content = ENV_FILE.read_text()
        
        # Remove existing analytics config if present
        lines = env_content.split('\n')
        lines = [line for line in lines if not line.startswith('ANALYTICS_')]
        env_content = '\n'.join(lines)
    
    # Add new config
    new_config = f"""
# Analytics Dashboard Authentication
ANALYTICS_ADMIN_USERNAME={username}
ANALYTICS_ADMIN_PASSWORD_HASH={password_hash}
ANALYTICS_SECRET_KEY={secret_key}
"""
    
    env_content += new_config
    
    # Write back to .env
    ENV_FILE.write_text(env_content)
    
    print("\n✅ Authentication configured successfully!")
    print(f"👤 Username: {username}")
    print("🔑 Password: (saved to .env)")
    print("\n📝 Next steps:")
    print("   1. Install dependencies: pip install fastapi uvicorn psycopg2-binary PyJWT bcrypt slowapi")
    print("   2. Run dashboard: python scripts/analytics_dashboard.py")
    print("   3. Access: http://localhost:8501")

if __name__ == "__main__":
    setup_auth()
