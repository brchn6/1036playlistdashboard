#!/usr/bin/env python3
"""
Analytics Dashboard - Secure internal platform for viewing radio analytics data.

Security features:
- Password authentication with bcrypt hashing
- JWT tokens with expiration
- Rate limiting on login attempts
- Input validation
- CORS restricted to localhost
- Runs on internal network only (127.0.0.1 or 192.168.x.x)

Usage:
    python scripts/analytics_dashboard.py
    
Access:
    http://localhost:8501
    Username: admin
    Password: (set in .env as ANALYTICS_ADMIN_PASSWORD)
"""

import os
import sys
import time
import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import psycopg2
from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import jwt
import bcrypt
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Load environment
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from supabase_client import get_setting

# Configuration
SECRET_KEY = get_setting("ANALYTICS_SECRET_KEY") or secrets.token_urlsafe(32)
ADMIN_USERNAME = get_setting("ANALYTICS_ADMIN_USERNAME") or "admin"
ADMIN_PASSWORD_HASH = get_setting("ANALYTICS_ADMIN_PASSWORD_HASH")
DB_PASSWORD = get_setting("SUPABASE_DB_PASSWORD")
SUPABASE_HOST = "db.ktewdeaegtukbosrgxmw.supabase.co"
SUPABASE_DB = "postgres"
SUPABASE_USER = "postgres"

# JWT settings
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Initialize password hash if not set
if not ADMIN_PASSWORD_HASH:
    print("⚠️  ANALYTICS_ADMIN_PASSWORD_HASH not set in .env")
    print("   Run: python scripts/setup_analytics_auth.py")
    sys.exit(1)

# FastAPI app
app = FastAPI(title="Radio Analytics Dashboard", docs_url=None, redoc_url=None)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - restrict to localhost and internal network only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
        "http://192.168.10.3:8501",  # head1 internal IP
        "http://192.168.10.*",  # Allow all devices on internal network
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Database connection
def get_db():
    """Get database connection."""
    if not DB_PASSWORD:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    try:
        conn = psycopg2.connect(
            host=SUPABASE_HOST,
            port=5432,
            dbname=SUPABASE_DB,
            user=SUPABASE_USER,
            password=DB_PASSWORD
        )
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection failed: {str(e)}")

# Authentication
class LoginRequest(BaseModel):
    username: str
    password: str

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_jwt_token(username: str) -> str:
    """Create JWT token."""
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[str]:
    """Verify JWT token and return username."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
) -> str:
    """Get current authenticated user."""
    username = verify_jwt_token(credentials.credentials)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    return username

# Routes
@app.post("/api/login")
@limiter.limit("5/minute")  # Rate limit login attempts
async def login(request: Request, login_data: LoginRequest):
    """Authenticate user and return JWT token."""
    # Validate input
    if not login_data.username or not login_data.password:
        raise HTTPException(status_code=400, detail="Username and password required")
    
    # Check credentials
    if login_data.username != ADMIN_USERNAME:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not verify_password(login_data.password, ADMIN_PASSWORD_HASH):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create token
    token = create_jwt_token(login_data.username)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": JWT_EXPIRATION_HOURS * 3600
    }

@app.get("/api/analytics/summary")
async def get_summary(current_user: str = Depends(get_current_user)):
    """Get analytics summary."""
    conn = get_db()
    try:
        cur = conn.cursor()
        
        # Total visits today
        cur.execute("""
            SELECT COUNT(*) FROM analytics_events 
            WHERE event_type = 'page_view' 
            AND created_at >= CURRENT_DATE
        """)
        visits_today = cur.fetchone()[0]
        
        # Total visits all time
        cur.execute("""
            SELECT COUNT(*) FROM analytics_events 
            WHERE event_type = 'page_view'
        """)
        visits_total = cur.fetchone()[0]
        
        # Average session duration
        cur.execute("""
            SELECT AVG((event_data->>'duration_seconds')::int) 
            FROM analytics_events 
            WHERE event_type = 'session_end'
        """)
        avg_duration = cur.fetchone()[0] or 0
        
        # Unique sessions today
        cur.execute("""
            SELECT COUNT(DISTINCT session_id) 
            FROM analytics_events 
            WHERE created_at >= CURRENT_DATE
        """)
        unique_sessions_today = cur.fetchone()[0]
        
        return {
            "visits_today": visits_today,
            "visits_total": visits_total,
            "avg_duration_seconds": int(avg_duration),
            "unique_sessions_today": unique_sessions_today
        }
    finally:
        conn.close()

@app.get("/api/analytics/by-country")
async def get_by_country(current_user: str = Depends(get_current_user)):
    """Get visits by country."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT country, COUNT(*) as visits 
            FROM analytics_events 
            WHERE event_type = 'page_view' AND country IS NOT NULL
            GROUP BY country 
            ORDER BY visits DESC
            LIMIT 20
        """)
        results = [{"country": row[0], "visits": row[1]} for row in cur.fetchall()]
        return results
    finally:
        conn.close()

@app.get("/api/analytics/recent")
async def get_recent(limit: int = 50, current_user: str = Depends(get_current_user)):
    """Get recent analytics events."""
    # Validate limit
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 100")
    
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                id, session_id, event_type, event_data, 
                user_agent, referrer, country, city, 
                screen_width, screen_height, language, created_at
            FROM analytics_events 
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        
        results = []
        for row in cur.fetchall():
            results.append({
                "id": row[0],
                "session_id": row[1],
                "event_type": row[2],
                "event_data": row[3],
                "user_agent": row[4],
                "referrer": row[5],
                "country": row[6],
                "city": row[7],
                "screen_width": row[8],
                "screen_height": row[9],
                "language": row[10],
                "created_at": row[11].isoformat() if row[11] else None
            })
        return results
    finally:
        conn.close()

@app.get("/api/analytics/timeline")
async def get_timeline(days: int = 7, current_user: str = Depends(get_current_user)):
    """Get visits timeline."""
    # Validate days
    if days < 1 or days > 30:
        raise HTTPException(status_code=400, detail="Days must be between 1 and 30")
    
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as visits
            FROM analytics_events 
            WHERE event_type = 'page_view'
            AND created_at >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """, (days,))
        
        results = [{"date": row[0].isoformat(), "visits": row[1]} for row in cur.fetchall()]
        return results
    finally:
        conn.close()

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the dashboard HTML."""
    html_path = PROJECT_ROOT / "docs" / "analytics_dashboard.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return HTMLResponse(content=html_path.read_text())

if __name__ == "__main__":
    import uvicorn
    
    print("🔒 Analytics Dashboard starting...")
    print("📊 Access: http://192.168.10.3:8501")
    print(f"👤 Username: {ADMIN_USERNAME}")
    print("🔑 Password: (see .env)")
    print("\n⚠️  This dashboard is for internal use only!")
    
    # Run on internal network (accessible from LAN)
    uvicorn.run(
        app,
        host="0.0.0.0",  # Bind to all interfaces for LAN access
        port=8501,
        log_level="info"
    )
