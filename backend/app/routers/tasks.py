import asyncio
import time
import uuid
import httpx
import random
from datetime import datetime
from typing import List, Dict, Optional, Any
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from app.database import get_db_connection
from app.chaos import chaos_config
from app.models import (
    CreateTaskRequest,
    TaskControlRequest,
    TaskStatusResponse,
    TaskLogItem
)
from app.automation.playwright_worker import PlaywrightWorker
from app.routers.ws import manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

class ActiveTaskRunner:
    def __init__(self, task_id: str, post_id: int, task_type: str, accounts: list, concurrency: int, delay_ms: int, headless: bool = True):
        self.task_id = task_id
        self.post_id = post_id
        self.task_type = task_type
        self.accounts = accounts
        self.concurrency = concurrency
        self.delay_ms = delay_ms
        self.headless = headless
        self.status = "PENDING"
        self.pause_event = asyncio.Event()
        self.pause_event.set() # Not paused initially
        self.cancel_requested = False
        self.success_count = 0
        self.failure_count = 0
        self.total = len(accounts)
        self.latest_screenshot = None

    async def run(self):
        self.status = "RUNNING"
        self._update_task_db_status("RUNNING")

        main_loop = asyncio.get_running_loop()

        if self.task_type == "PLAYWRIGHT":
            # Run in a background thread with WindowsProactorEventLoopPolicy to support subprocesses on Windows
            await asyncio.to_thread(self._run_playwright_sync, main_loop)
            return

        # API Mode (Fast execution directly on main loop)
        semaphore = asyncio.Semaphore(self.concurrency)

        async def worker_job(acc):
            if self.cancel_requested:
                return

            await self.pause_event.wait()
            if self.cancel_requested:
                return

            async with semaphore:
                if self.delay_ms > 0:
                    await asyncio.sleep(self.delay_ms / 1000.0)

                t_start = time.perf_counter()
                success = False
                error_msg = None

                # Injected chaos in API mode
                if chaos_config.get("enabled"):
                    c_delay = chaos_config.get("delay_ms", 0)
                    if c_delay > 0:
                        await asyncio.sleep(c_delay / 1000.0)
                    if random.random() < chaos_config.get("fail_rate", 0.0):
                        error_msg = "Chaos Fault Injected: HTTP 500 (Simulated Server Error)"

                user_id = acc["id"]
                if not error_msg:
                    try:
                        conn = get_db_connection()
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM likes WHERE post_id = ? AND user_id = ?", (self.post_id, user_id))
                        if cur.fetchone():
                            success = False
                            error_msg = "Duplicate: already liked"
                        else:
                            cur.execute("""
                                INSERT INTO likes (post_id, user_id, method, task_id)
                                VALUES (?, ?, 'API', ?)
                            """, (self.post_id, user_id, self.task_id))
                            cur.execute("UPDATE posts SET likes_count = likes_count + 1 WHERE id = ?", (self.post_id,))
                            conn.commit()
                            success = True
                        conn.close()
                    except Exception as ex:
                        success = False
                        error_msg = str(ex)

                duration = round((time.perf_counter() - t_start) * 1000, 2)

                if success:
                    self.success_count += 1
                else:
                    self.failure_count += 1

                self._log_account_result(acc["id"], acc["username"], "SUCCESS" if success else "FAILED", duration, error_msg)

                asyncio.create_task(manager.broadcast({
                    "type": "task_progress",
                    "data": {
                        "task_id": self.task_id,
                        "status": self.status,
                        "total": self.total,
                        "completed": self.success_count + self.failure_count,
                        "success_count": self.success_count,
                        "failure_count": self.failure_count,
                        "latest_log": {
                            "username": acc["username"],
                            "status": "SUCCESS" if success else "FAILED",
                            "duration_ms": duration,
                            "error": error_msg,
                            "screenshot": None
                        }
                    }
                }))

        tasks = [worker_job(acc) for acc in self.accounts]
        await asyncio.gather(*tasks, return_exceptions=True)

        if self.cancel_requested:
            self.status = "CANCELLED"
        else:
            self.status = "COMPLETED"

        self._update_task_db_status(self.status)

        await manager.broadcast({
            "type": "task_completed",
            "data": {
                "task_id": self.task_id,
                "status": self.status,
                "success_count": self.success_count,
                "failure_count": self.failure_count
            }
        })

    def _run_playwright_sync(self, main_loop):
        import sys
        if sys.platform == "win32":
            loop = asyncio.WindowsProactorEventLoopPolicy().new_event_loop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_playwright_async(main_loop))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    async def _run_playwright_async(self, main_loop):
        base_url = "http://127.0.0.1:8000"
        playwright_worker = PlaywrightWorker(base_url=base_url, headless=self.headless)
        try:
            await playwright_worker.start()
        except Exception as e:
            self.status = "CANCELLED"
            self._update_task_db_status("CANCELLED", error_summary=f"Playwright start failed: {str(e)}")
            asyncio.run_coroutine_threadsafe(manager.broadcast({
                "type": "task_completed",
                "data": {
                    "task_id": self.task_id,
                    "status": "CANCELLED",
                    "success_count": 0,
                    "failure_count": self.total,
                    "error": str(e)
                }
            }), main_loop)
            return

        semaphore = asyncio.Semaphore(self.concurrency)

        async def worker_job(acc):
            if self.cancel_requested:
                return

            await self.pause_event.wait()
            if self.cancel_requested:
                return

            async with semaphore:
                if self.delay_ms > 0:
                    await asyncio.sleep(self.delay_ms / 1000.0)

                async def handle_frame(shot_b64, stage_name):
                    self.latest_screenshot = shot_b64
                    try:
                        import base64
                        import os
                        raw_b64 = shot_b64.split(",", 1)[-1]
                        raw_bytes = base64.b64decode(raw_b64)
                        shot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
                        os.makedirs(shot_dir, exist_ok=True)
                        with open(os.path.join(shot_dir, f"{self.task_id}.jpg"), "wb") as fp:
                            fp.write(raw_bytes)
                        with open(os.path.join(shot_dir, "latest.jpg"), "wb") as fp:
                            fp.write(raw_bytes)
                    except Exception:
                        pass
                    asyncio.run_coroutine_threadsafe(manager.broadcast({
                        "type": "task_screenshot",
                        "data": {
                            "task_id": self.task_id,
                            "screenshot": shot_b64,
                            "stage": stage_name,
                            "username": acc["username"]
                        }
                    }), main_loop)

                res = await playwright_worker.execute_like_flow(
                    username=acc["username"],
                    password="password123",
                    post_id=self.post_id,
                    task_id=self.task_id,
                    token=acc.get("session_token"),
                    target_url=f"{base_url}/mock-social",
                    capture_screenshot=True,
                    on_frame_callback=handle_frame
                )

                success = res["success"]
                error_msg = res.get("error")
                duration = res.get("duration_ms", 0.0)
                screenshot = res.get("screenshot")
                if screenshot:
                    self.latest_screenshot = screenshot
                    try:
                        import base64
                        import os
                        raw_b64 = screenshot.split(",", 1)[-1]
                        raw_bytes = base64.b64decode(raw_b64)
                        shot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
                        os.makedirs(shot_dir, exist_ok=True)
                        with open(os.path.join(shot_dir, f"{self.task_id}.jpg"), "wb") as fp:
                            fp.write(raw_bytes)
                        with open(os.path.join(shot_dir, "latest.jpg"), "wb") as fp:
                            fp.write(raw_bytes)
                    except Exception:
                        pass

                if success:
                    self.success_count += 1
                else:
                    self.failure_count += 1

                self._log_account_result(acc["id"], acc["username"], "SUCCESS" if success else "FAILED", duration, error_msg)

                # Broadcast progress via main loop
                asyncio.run_coroutine_threadsafe(manager.broadcast({
                    "type": "task_progress",
                    "data": {
                        "task_id": self.task_id,
                        "status": self.status,
                        "total": self.total,
                        "completed": self.success_count + self.failure_count,
                        "success_count": self.success_count,
                        "failure_count": self.failure_count,
                        "screenshot": screenshot,
                        "latest_log": {
                            "username": acc["username"],
                            "status": "SUCCESS" if success else "FAILED",
                            "duration_ms": duration,
                            "error": error_msg,
                            "screenshot": screenshot
                        }
                    }
                }), main_loop)

        tasks = [worker_job(acc) for acc in self.accounts]
        await asyncio.gather(*tasks, return_exceptions=True)

        try:
            await playwright_worker.stop()
        except Exception:
            pass

        if self.cancel_requested:
            self.status = "CANCELLED"
        else:
            self.status = "COMPLETED"

        self._update_task_db_status(self.status)

        asyncio.run_coroutine_threadsafe(manager.broadcast({
            "type": "task_completed",
            "data": {
                "task_id": self.task_id,
                "status": self.status,
                "success_count": self.success_count,
                "failure_count": self.failure_count
            }
        }), main_loop)

    def pause(self):
        self.status = "PAUSED"
        self.pause_event.clear()
        self._update_task_db_status("PAUSED")

    def resume(self):
        self.status = "RUNNING"
        self.pause_event.set()
        self._update_task_db_status("RUNNING")

    def cancel(self):
        self.cancel_requested = True
        self.pause_event.set() # Unblock if paused
        self.status = "CANCELLED"
        self._update_task_db_status("CANCELLED")

    def _update_task_db_status(self, status: str, error_summary: Optional[str] = None):
        try:
            conn = get_db_connection()
            conn.execute("""
                UPDATE tasks
                SET status = ?, success_count = ?, failure_count = ?, updated_at = CURRENT_TIMESTAMP, error_summary = ?
                WHERE id = ?
            """, (status, self.success_count, self.failure_count, error_summary, self.task_id))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _log_account_result(self, user_id: int, username: str, status: str, duration_ms: float, error_msg: Optional[str]):
        try:
            conn = get_db_connection()
            conn.execute("""
                INSERT INTO task_logs (task_id, user_id, username, status, duration_ms, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (self.task_id, user_id, username, status, duration_ms, error_msg))
            conn.commit()
            conn.close()
        except Exception:
            pass

active_runners: Dict[str, ActiveTaskRunner] = {}

@router.get("", response_model=List[TaskStatusResponse])
def list_tasks():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, type, post_id, total_accounts, concurrency, delay_ms, status,
               success_count, failure_count, created_at, updated_at, error_summary
        FROM tasks
        ORDER BY created_at DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.post("", response_model=TaskStatusResponse)
async def create_task(req: CreateTaskRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    conn = get_db_connection()
    cursor = conn.cursor()

    # Query matching accounts
    query = """
        SELECT u.id, u.username, s.token as session_token
        FROM users u
        LEFT JOIN sessions s ON s.user_id = u.id AND s.is_active = 1
        WHERE u.status = 'ACTIVE' AND u.username != 'admin'
    """
    params = []
    if req.group_tag:
        query += " AND u.group_tag = ?"
        params.append(req.group_tag)

    query += " ORDER BY u.id ASC LIMIT ?"
    params.append(req.total_accounts)

    cursor.execute(query, params)
    accounts = [dict(r) for r in cursor.fetchall()]

    if not accounts:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail="No active test accounts available matching criteria. Please generate test accounts first."
        )

    total_matched = len(accounts)

    cursor.execute("""
        INSERT INTO tasks (id, type, post_id, total_accounts, concurrency, delay_ms, status, success_count, failure_count)
        VALUES (?, ?, ?, ?, ?, ?, 'PENDING', 0, 0)
    """, (task_id, req.type, req.post_id, total_matched, req.concurrency, req.delay_ms))
    conn.commit()
    conn.close()

    # Create task runner
    runner = ActiveTaskRunner(
        task_id=task_id,
        post_id=req.post_id,
        task_type=req.type,
        accounts=accounts,
        concurrency=req.concurrency,
        delay_ms=req.delay_ms,
        headless=req.headless
    )
    active_runners[task_id] = runner

    # Launch task asynchronously
    asyncio.create_task(runner.run())

    return TaskStatusResponse(
        id=task_id,
        type=req.type,
        post_id=req.post_id,
        total_accounts=total_matched,
        concurrency=req.concurrency,
        delay_ms=req.delay_ms,
        status="RUNNING",
        success_count=0,
        failure_count=0,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat()
    )

@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return dict(row)

@router.post("/{task_id}/control")
def control_task(task_id: str, req: TaskControlRequest):
    runner = active_runners.get(task_id)
    if not runner:
        # Check if exists in db
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")
        if req.action == "cancel":
            conn = get_db_connection()
            conn.execute("UPDATE tasks SET status = 'CANCELLED' WHERE id = ?", (task_id,))
            conn.commit()
            conn.close()
            return {"success": True, "task_id": task_id, "status": "CANCELLED"}
        raise HTTPException(status_code=400, detail="Task is not currently running in memory")

    if req.action == "pause":
        runner.pause()
    elif req.action == "resume":
        runner.resume()
    elif req.action == "cancel":
        runner.cancel()
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {req.action}")

    return {"success": True, "task_id": task_id, "status": runner.status}

@router.get("/{task_id}/logs", response_model=List[TaskLogItem])
def get_task_logs(task_id: str, limit: int = 100):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, task_id, user_id, username, status, duration_ms, error_message, created_at
        FROM task_logs
        WHERE task_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (task_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@router.get("/{task_id}/screenshot")
def get_task_screenshot(task_id: str):
    runner = active_runners.get(task_id)
    if runner and runner.latest_screenshot:
        return {
            "screenshot": runner.latest_screenshot,
            "available": True
        }

    # Fallback to persistent disk cache for this task_id
    try:
        import os
        import base64
        shot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screenshots")
        task_fpath = os.path.join(shot_dir, f"{task_id}.jpg")
        if os.path.exists(task_fpath):
            with open(task_fpath, "rb") as fp:
                b64 = base64.b64encode(fp.read()).decode("utf-8")
                return {
                    "screenshot": f"data:image/jpeg;base64,{b64}",
                    "available": True
                }
    except Exception:
        pass

    return {
        "screenshot": None,
        "available": False
    }
