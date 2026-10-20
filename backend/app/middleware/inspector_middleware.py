import time
import json
import uuid
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from app.database import get_db_connection
from app.routers.ws import manager
from app.chaos import evaluate_chaos_for_path

class InspectorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # We only inspect /api routes to avoid noise from static assets or docs
        path = request.url.path
        if not path.startswith("/api") or path.startswith("/api/inspector/logs") or path.startswith("/api/ws"):
            return await call_next(request)

        req_id = f"req_{uuid.uuid4().hex[:12]}"
        start_time = time.perf_counter()
        timestamp = datetime.utcnow().isoformat() + "Z"

        # Capture sanitized request headers
        headers = dict(request.headers)
        masked_headers = {}
        for k, v in headers.items():
            if k.lower() in ["authorization", "cookie", "token"]:
                if len(v) > 12:
                    masked_headers[k] = v[:7] + "****" + v[-4:]
                else:
                    masked_headers[k] = "****"
            else:
                masked_headers[k] = v

        # Capture request body if available
        req_body = ""
        try:
            body_bytes = await request.body()
            if body_bytes:
                req_body = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass

        # Prepare request state for custom annotations from endpoint handlers
        request.state.inspector_id = req_id
        request.state.session_validation = {
            "evaluated": False,
            "status": "NOT_APPLICABLE",
            "token": None,
            "user_id": None,
            "username": None
        }
        request.state.db_delta = {
            "performed": False,
            "action": None,
            "rows_affected": 0,
            "details": None
        }

        # Call the endpoint with chaos evaluation
        response = None
        error_detail = None
        try:
            should_fail, injected_delay = await evaluate_chaos_for_path(path)
            if should_fail:
                response = Response(
                    content=json.dumps({"detail": "Chaos Simulation: Injected 500 Internal Server Error", "error_code": "CHAOS_INJECTED_FAULT"}),
                    status_code=500,
                    media_type="application/json"
                )
            else:
                response = await call_next(request)
        except Exception as exc:
            error_detail = str(exc)
            raise exc
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            status_code = response.status_code if response else 500

            # Capture response body
            resp_body_text = ""
            if response and hasattr(response, "body"):
                try:
                    resp_body_text = response.body.decode("utf-8", errors="replace")
                except Exception:
                    resp_body_text = "<binary or streaming response>"
            elif response and isinstance(response, StreamingResponse):
                # We can capture content from streaming response if needed or note it
                resp_body_text = "<streaming response>"

            # Read annotations placed by endpoints
            sess_val = getattr(request.state, "session_validation", {})
            db_delta = getattr(request.state, "db_delta", {})

            # Construct the 7-layer lifecycle steps (Primary Traditional Chinese, Secondary English)
            lifecycle = [
                {
                    "stage": 1,
                    "name": "瀏覽器 / 客戶端 (Browser / Client)",
                    "status": "COMPLETED",
                    "description": "客戶端發起互動操作（源自前端 UI 點擊或 Playwright 自動化隔離 Context）/ Client initiated HTTP request from browser or automated worker.",
                    "data": {
                        "client_host": request.client.host if request.client else "127.0.0.1",
                        "user_agent": masked_headers.get("user-agent", "Unknown"),
                        "origin": masked_headers.get("origin", "Localhost")
                    }
                },
                {
                    "stage": 2,
                    "name": "HTTP 請求傳輸 (HTTP Request)",
                    "status": "COMPLETED",
                    "description": f"傳輸 {request.method} {path} 與遮罩請求標頭 / Transmitted {request.method} {path} with headers and payload.",
                    "data": {
                        "method": request.method,
                        "url": str(request.url),
                        "headers": masked_headers,
                        "body": req_body[:500] if req_body else None
                    }
                },
                {
                    "stage": 3,
                    "name": "FastAPI 路由引擎 (FastAPI Engine)",
                    "status": "COMPLETED" if status_code != 429 else "RATE_LIMITED",
                    "description": "通過 FastAPI 路由分發與 Rate Limiting 滑動視窗檢查 / Routed through FastAPI router and rate limiting middleware.",
                    "data": {
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": duration_ms
                    }
                },
                {
                    "stage": 4,
                    "name": "Session 憑證驗證 (Session Validation)",
                    "status": "VALID" if sess_val.get("status") == "VALID" else sess_val.get("status", "BYPASSED"),
                    "description": "核對 Bearer Session Token 與資料庫有效狀態 / Validated bearer session token against active sessions table.",
                    "data": sess_val
                },
                {
                    "stage": 5,
                    "name": "SQLite 原子交易 (SQLite Transaction)",
                    "status": "COMMITTED" if db_delta.get("performed") else "SKIPPED",
                    "description": "執行 SQLite WAL 交易與約束檢查 / Executed SQLite write/read in WAL mode with atomic constraints.",
                    "data": db_delta
                },
                {
                    "stage": 6,
                    "name": "HTTP 回應封裝 (HTTP Response)",
                    "status": "SUCCESS" if 200 <= status_code < 400 else "ERROR",
                    "description": f"返回 HTTP {status_code} 與 JSON 數據負載 / Returned HTTP {status_code} with JSON payload.",
                    "data": {
                        "status_code": status_code,
                        "response_preview": resp_body_text[:500] if resp_body_text else None
                    }
                },
                {
                    "stage": 7,
                    "name": "UI 更新與即時廣播 (UI Update & Broadcast)",
                    "status": "BROADCASTED" if status_code == 200 and db_delta.get("performed") else "NO_BROADCAST",
                    "description": "觸發 WebSocket 廣播通知前端即時同步按讚數 / WebSocket sync triggered to update post like counters and inspector across clients.",
                    "data": {
                        "websocket_notified": status_code == 200 and db_delta.get("performed"),
                        "event_type": "post_liked" if "/like" in path else "state_updated"
                    }
                }
            ]

            user_id = sess_val.get("user_id")
            username = sess_val.get("username")

            # Persist to database in a safe non-blocking way
            try:
                conn = get_db_connection()
                conn.execute("""
                    INSERT INTO inspector_logs (
                        id, timestamp, method, path, status_code, user_id, username,
                        request_headers, request_body, response_body, session_validation,
                        db_delta, duration_ms, lifecycle_stages
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req_id, timestamp, request.method, path, status_code, user_id, username,
                    json.dumps(masked_headers), req_body[:1000], resp_body_text[:1000],
                    json.dumps(sess_val), json.dumps(db_delta), duration_ms, json.dumps(lifecycle)
                ))
                # Prune logs older than last 500 to keep DB light and responsive
                conn.execute("""
                    DELETE FROM inspector_logs WHERE id NOT IN (
                        SELECT id FROM inspector_logs ORDER BY timestamp DESC LIMIT 500
                    )
                """)
                conn.commit()
                conn.close()
            except Exception as e:
                pass

            # Broadcast log to connected inspector dashboards via WebSocket
            try:
                import asyncio
                log_summary = {
                    "type": "inspector_log",
                    "data": {
                        "id": req_id,
                        "timestamp": timestamp,
                        "method": request.method,
                        "path": path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "username": username or "anonymous",
                        "session_status": sess_val.get("status", "N/A"),
                        "db_action": db_delta.get("action", "NONE")
                    }
                }
                # Fire and forget websocket broadcast
                asyncio.create_task(manager.broadcast(log_summary))
            except Exception:
                pass

        return response
