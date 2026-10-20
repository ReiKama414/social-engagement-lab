import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from app.database import get_db_connection

router = APIRouter(prefix="/api/inspector", tags=["inspector"])

@router.get("/logs")
def list_inspector_logs(
    method: Optional[str] = None,
    status_code: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if method:
        conditions.append("method = ?")
        params.append(method.upper())

    if status_code:
        conditions.append("status_code = ?")
        params.append(status_code)

    if search:
        conditions.append("(path LIKE ? OR username LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = " AND ".join(conditions)

    cursor.execute(f"SELECT COUNT(*) as total FROM inspector_logs WHERE {where_clause}", params)
    total = cursor.fetchone()["total"]

    cursor.execute(f"""
        SELECT id, timestamp, method, path, status_code, user_id, username,
               duration_ms, session_validation, db_delta
        FROM inspector_logs
        WHERE {where_clause}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset])
    rows = cursor.fetchall()
    conn.close()

    items = []
    for r in rows:
        sess_val = json.loads(r["session_validation"]) if r["session_validation"] else {}
        db_delta = json.loads(r["db_delta"]) if r["db_delta"] else {}
        items.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "method": r["method"],
            "path": r["path"],
            "status_code": r["status_code"],
            "user_id": r["user_id"],
            "username": r["username"],
            "duration_ms": r["duration_ms"],
            "session_status": sess_val.get("status", "N/A"),
            "db_action": db_delta.get("action", "NONE")
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items
    }

@router.get("/logs/{log_id}")
def get_inspector_log(log_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM inspector_logs WHERE id = ?", (log_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Inspector log entry not found")

    req_headers = json.loads(row["request_headers"]) if row["request_headers"] else {}
    req_body = row["request_body"] or ""
    method = row["method"]
    path = row["path"]
    duration = row["duration_ms"]

    curl_cmd = f"curl -X {method} 'http://127.0.0.1:8000{path}'"
    for hk, hv in req_headers.items():
        if hk.lower() not in ["host", "content-length"]:
            curl_cmd += f" \\\n  -H '{hk}: {hv}'"
    if req_body:
        escaped_body = req_body.replace("'", "\\'")
        curl_cmd += f" \\\n  --data '{escaped_body}'"

    waterfall = {
        "dns_network_ms": round(max(0.1, duration * 0.12), 2),
        "route_matching_ms": round(max(0.1, duration * 0.10), 2),
        "session_validation_ms": round(max(0.1, duration * 0.35), 2),
        "sqlite_transaction_ms": round(max(0.1, duration * 0.33), 2),
        "serialization_ms": round(max(0.1, duration * 0.10), 2),
        "total_ms": duration
    }

    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "method": row["method"],
        "path": row["path"],
        "status_code": row["status_code"],
        "user_id": row["user_id"],
        "username": row["username"],
        "request_headers": req_headers,
        "request_body": row["request_body"],
        "response_body": row["response_body"],
        "session_validation": json.loads(row["session_validation"]) if row["session_validation"] else {},
        "db_delta": json.loads(row["db_delta"]) if row["db_delta"] else {},
        "duration_ms": duration,
        "lifecycle_stages": json.loads(row["lifecycle_stages"]) if row["lifecycle_stages"] else [],
        "curl_command": curl_cmd,
        "timing_waterfall": waterfall
    }

@router.post("/clear")
def clear_inspector_logs():
    conn = get_db_connection()
    conn.execute("DELETE FROM inspector_logs")
    conn.commit()
    conn.close()
    return {"success": True, "message": "Inspector logs cleared."}
