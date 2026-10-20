import time
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from app.database import get_db_connection
from app.models import (
    BatchAccountCreateRequest,
    BatchAccountActionRequest,
    AccountStatsResponse
)

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

@router.get("")
def list_accounts(
    search: Optional[str] = None,
    group_tag: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if search:
        conditions.append("(u.username LIKE ? OR u.display_name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if group_tag:
        conditions.append("u.group_tag = ?")
        params.append(group_tag)

    if status:
        conditions.append("u.status = ?")
        params.append(status)

    where_clause = " AND ".join(conditions)

    # Get total count
    cursor.execute(f"SELECT COUNT(*) as total FROM users u WHERE {where_clause}", params)
    total = cursor.fetchone()["total"]

    # Fetch rows with session token if present
    query = f"""
        SELECT u.id, u.username, u.display_name, u.avatar_url, u.status, u.group_tag, u.created_at,
               s.token as session_token, s.expires_at as session_expires_at, s.is_active as session_is_active
        FROM users u
        LEFT JOIN sessions s ON s.user_id = u.id AND s.is_active = 1
        WHERE {where_clause}
        ORDER BY u.id DESC
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [limit, offset])
    rows = cursor.fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "username": r["username"],
            "display_name": r["display_name"],
            "avatar_url": r["avatar_url"],
            "status": r["status"],
            "group_tag": r["group_tag"],
            "created_at": str(r["created_at"]),
            "session_token": r["session_token"],
            "session_active": bool(r["session_is_active"]) if r["session_is_active"] is not None else False,
            "session_expires_at": r["session_expires_at"]
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items
    }

@router.get("/stats", response_model=AccountStatsResponse)
def get_account_stats():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM users")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) as active FROM users WHERE status = 'ACTIVE'")
    active = cursor.fetchone()["active"]

    cursor.execute("SELECT COUNT(*) as disabled FROM users WHERE status != 'ACTIVE'")
    disabled = cursor.fetchone()["disabled"]

    now_iso = datetime.utcnow().isoformat() + "Z"
    cursor.execute("SELECT COUNT(*) as expired FROM sessions WHERE expires_at < ? OR is_active = 0", (now_iso,))
    expired = cursor.fetchone()["expired"]

    cursor.execute("SELECT group_tag, COUNT(*) as count FROM users GROUP BY group_tag")
    group_rows = cursor.fetchall()
    group_counts = {r["group_tag"]: r["count"] for r in group_rows}

    conn.close()

    return AccountStatsResponse(
        total_accounts=total,
        active_accounts=active,
        disabled_accounts=disabled,
        expired_sessions=expired,
        group_counts=group_counts
    )

@router.post("/generate")
def generate_accounts(req: BatchAccountCreateRequest):
    """
    High performance batch account generator supporting up to 10,000 accounts.
    Uses multi-row batched executemany for sub-second execution.
    """
    start_time = time.perf_counter()
    count = req.count
    group = req.group_tag or "batch"
    prefix = req.prefix or "bot"

    conn = get_db_connection()
    cursor = conn.cursor()

    # Find highest existing id or sequence
    cursor.execute("SELECT MAX(id) as max_id FROM users")
    max_row = cursor.fetchone()
    base_id = (max_row["max_id"] or 0) + 1

    common_pwd_hash = hashlib.sha256("password123".encode()).hexdigest()
    now_dt = datetime.utcnow()
    expires_at = (now_dt + timedelta(days=7)).isoformat() + "Z"

    batch_users = []
    batch_sessions = []
    timestamp_suffix = hex(int(time.time()))[4:]

    for i in range(count):
        idx = base_id + i
        username = f"{prefix}_{idx}_{timestamp_suffix}"
        disp_name = f"Agent {idx}"
        avatar = f"https://api.dicebear.com/7.x/bottts/svg?seed={username}"
        batch_users.append((username, disp_name, avatar, common_pwd_hash, "ACTIVE", group))

    # Fast bulk insert users
    cursor.executemany("""
        INSERT INTO users (username, display_name, avatar_url, password_hash, status, group_tag)
        VALUES (?, ?, ?, ?, ?, ?)
    """, batch_users)

    # Get the inserted user IDs
    cursor.execute("""
        SELECT id, username FROM users WHERE group_tag = ? AND id >= ? ORDER BY id ASC
    """, (group, base_id))
    inserted_rows = cursor.fetchall()

    if req.pre_generate_sessions:
        for r in inserted_rows:
            uid = r["id"]
            token = f"sess_{uuid.uuid4().hex}"
            batch_sessions.append((token, uid, expires_at, 1))

        cursor.executemany("""
            INSERT INTO sessions (token, user_id, expires_at, is_active)
            VALUES (?, ?, ?, ?)
        """, batch_sessions)

    conn.commit()
    conn.close()

    elapsed = round(time.perf_counter() - start_time, 3)

    return {
        "success": True,
        "created_count": count,
        "group_tag": group,
        "elapsed_seconds": elapsed,
        "message": f"Successfully generated {count} test accounts in {elapsed}s with active sessions."
    }

@router.post("/bulk-action")
def bulk_account_action(req: BatchAccountActionRequest):
    conn = get_db_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if req.account_ids:
        placeholders = ",".join(["?"] * len(req.account_ids))
        conditions.append(f"id IN ({placeholders})")
        params.extend(req.account_ids)
    elif req.group_tag:
        conditions.append("group_tag = ?")
        params.append(req.group_tag)
    elif req.status:
        conditions.append("status = ?")
        params.append(req.status)
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Must specify account_ids, group_tag, or status")

    where_clause = " AND ".join(conditions)

    if req.action == "enable":
        cursor.execute(f"UPDATE users SET status = 'ACTIVE' WHERE {where_clause}", params)
        affected = cursor.rowcount
    elif req.action == "disable":
        # Don't disable admin
        cursor.execute(f"UPDATE users SET status = 'DISABLED' WHERE {where_clause} AND username != 'admin'", params)
        affected = cursor.rowcount
    elif req.action == "expire_sessions":
        past_time = (datetime.utcnow() - timedelta(hours=1)).isoformat() + "Z"
        cursor.execute(f"""
            UPDATE sessions SET expires_at = ?, is_active = 0
            WHERE user_id IN (SELECT id FROM users WHERE {where_clause})
        """, [past_time] + params)
        affected = cursor.rowcount
    elif req.action == "delete":
        # Don't delete admin
        cursor.execute(f"DELETE FROM users WHERE {where_clause} AND username != 'admin'", params)
        affected = cursor.rowcount
    else:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    conn.commit()
    conn.close()

    return {
        "success": True,
        "action": req.action,
        "affected_rows": affected
    }

@router.get("/export")
def export_accounts(format: str = "json", group_tag: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
        SELECT u.id, u.username, u.display_name, u.status, u.group_tag, u.created_at,
               s.token as session_token
        FROM users u
        LEFT JOIN sessions s ON s.user_id = u.id AND s.is_active = 1
        WHERE u.username != 'admin'
    """
    params = []
    if group_tag:
        query += " AND u.group_tag = ?"
        params.append(group_tag)
    query += " ORDER BY u.id ASC"

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if format.lower() == "csv":
        import io
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "username", "display_name", "status", "group_tag", "session_token", "created_at"])
        for r in rows:
            writer.writerow([r["id"], r["username"], r["display_name"], r["status"], r["group_tag"], r["session_token"] or "", r["created_at"]])
        from fastapi.responses import Response
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=accounts_export.csv"}
        )

    return {"total": len(rows), "accounts": rows}
