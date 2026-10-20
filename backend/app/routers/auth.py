import hashlib
import uuid
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from app.database import get_db_connection
from app.models import RegisterRequest, LoginRequest, AuthResponse, UserResponse, ExpireSessionRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def get_current_user_optional(request: Request, authorization: Optional[str] = Header(None)) -> Optional[dict]:
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    elif "session_token" in request.cookies:
        token = request.cookies.get("session_token")

    val_result = {
        "evaluated": True,
        "token": token[:8] + "..." if token and len(token) > 8 else token,
        "status": "MISSING_TOKEN",
        "user_id": None,
        "username": None,
        "reason": "No authorization bearer token or cookie provided"
    }

    if not token:
        request.state.session_validation = val_result
        return None

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.token, s.user_id, s.expires_at, s.is_active,
               u.id, u.username, u.display_name, u.avatar_url, u.status, u.group_tag, u.created_at
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.token = ?
    """, (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        val_result["status"] = "INVALID_TOKEN"
        val_result["reason"] = "Token not found in active session store"
        request.state.session_validation = val_result
        return None

    # Check is_active
    if not row["is_active"]:
        val_result["status"] = "REVOKED"
        val_result["reason"] = "Session was explicitly revoked or logged out"
        request.state.session_validation = val_result
        return None

    # Check expiration
    expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", ""))
    if expires_at < datetime.utcnow():
        val_result["status"] = "EXPIRED"
        val_result["reason"] = f"Session expired at {row['expires_at']}"
        val_result["user_id"] = row["id"]
        val_result["username"] = row["username"]
        request.state.session_validation = val_result
        return None

    # Check user status
    if row["status"] != "ACTIVE":
        val_result["status"] = f"USER_{row['status']}"
        val_result["reason"] = f"Account state is currently {row['status']}"
        val_result["user_id"] = row["id"]
        val_result["username"] = row["username"]
        request.state.session_validation = val_result
        return None

    val_result["status"] = "VALID"
    val_result["reason"] = "Session verified and active"
    val_result["user_id"] = row["id"]
    val_result["username"] = row["username"]
    request.state.session_validation = val_result

    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "avatar_url": row["avatar_url"],
        "status": row["status"],
        "group_tag": row["group_tag"],
        "created_at": str(row["created_at"]),
        "session_token": token
    }

def get_current_user(request: Request, user: Optional[dict] = Depends(get_current_user_optional)) -> dict:
    if not user:
        sess_val = getattr(request.state, "session_validation", {})
        status_msg = sess_val.get("reason", "Authentication required")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Session validation failed: {status_msg}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

@router.post("/register", response_model=AuthResponse)
def register(req: RegisterRequest):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = ?", (req.username,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Username already exists")

    pwd_hash = hash_password(req.password)
    disp_name = req.display_name or req.username
    avatar = req.avatar_url or f"https://api.dicebear.com/7.x/bottts/svg?seed={req.username}"

    cursor.execute("""
        INSERT INTO users (username, display_name, avatar_url, password_hash, status, group_tag)
        VALUES (?, ?, ?, ?, 'ACTIVE', ?)
    """, (req.username, disp_name, avatar, pwd_hash, req.group_tag or "standard"))
    user_id = cursor.lastrowid

    # Create session
    token = f"sess_{uuid.uuid4().hex}"
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
    cursor.execute("""
        INSERT INTO sessions (token, user_id, expires_at, is_active)
        VALUES (?, ?, ?, 1)
    """, (token, user_id, expires_at))

    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    conn.commit()
    conn.close()

    user_data = UserResponse(
        id=user_row["id"],
        username=user_row["username"],
        display_name=user_row["display_name"],
        avatar_url=user_row["avatar_url"],
        status=user_row["status"],
        group_tag=user_row["group_tag"],
        created_at=str(user_row["created_at"])
    )
    return AuthResponse(token=token, user=user_data, expires_at=expires_at)

@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE username = ?", (req.username,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user["password_hash"] != hash_password(req.password):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user["status"] != "ACTIVE":
        conn.close()
        raise HTTPException(status_code=403, detail=f"Account is {user['status']}")

    token = f"sess_{uuid.uuid4().hex}"
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat() + "Z"
    cursor.execute("""
        INSERT INTO sessions (token, user_id, expires_at, is_active)
        VALUES (?, ?, ?, 1)
    """, (token, user["id"], expires_at))

    conn.commit()
    conn.close()

    user_data = UserResponse(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        avatar_url=user["avatar_url"],
        status=user["status"],
        group_tag=user["group_tag"],
        created_at=str(user["created_at"])
    )
    return AuthResponse(token=token, user=user_data, expires_at=expires_at)

@router.get("/me", response_model=UserResponse)
def get_me(current_user: dict = Depends(get_current_user)):
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        display_name=current_user["display_name"],
        avatar_url=current_user["avatar_url"],
        status=current_user["status"],
        group_tag=current_user["group_tag"],
        created_at=current_user["created_at"]
    )

@router.post("/logout")
def logout(current_user: dict = Depends(get_current_user)):
    token = current_user.get("session_token")
    if token:
        conn = get_db_connection()
        conn.execute("UPDATE sessions SET is_active = 0 WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    return {"success": True, "message": "Successfully logged out"}

@router.post("/expire-session")
def expire_session(req: ExpireSessionRequest):
    """Utility endpoint to artificially expire sessions for testing validation error handling."""
    conn = get_db_connection()
    cursor = conn.cursor()
    past_time = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "Z"

    if req.token:
        cursor.execute("UPDATE sessions SET expires_at = ? WHERE token = ?", (past_time, req.token))
    elif req.username:
        cursor.execute("""
            UPDATE sessions SET expires_at = ?
            WHERE user_id IN (SELECT id FROM users WHERE username = ?)
        """, (past_time, req.username))
    else:
        # Expire all sessions for test accounts
        cursor.execute("UPDATE sessions SET expires_at = ? WHERE user_id > 1", (past_time,))

    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return {"success": True, "expired_sessions_count": affected}
