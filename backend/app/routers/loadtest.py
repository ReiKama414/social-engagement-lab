import asyncio
import time
import math
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from app.database import get_db_connection
from app.models import StartLoadTestRequest, LoadTestMetricResponse
from app.routers.ws import manager

router = APIRouter(prefix="/api/loadtest", tags=["loadtest"])

class LoadTestEngine:
    def __init__(self):
        self.running = False
        self.stop_requested = False
        self.post_id: int = 1
        self.concurrency: int = 50
        self.total_target: int = 1000
        self.start_time: float = 0.0
        self.end_time: float = 0.0

        self.success_count = 0
        self.failure_count = 0
        self.latencies: List[float] = []
        self.errors_breakdown: Dict[str, int] = {}
        self.db_writes = 0

    def reset(self):
        self.running = False
        self.stop_requested = False
        self.success_count = 0
        self.failure_count = 0
        self.latencies = []
        self.errors_breakdown = {}
        self.db_writes = 0
        self.start_time = 0.0
        self.end_time = 0.0

    def get_metrics(self) -> LoadTestMetricResponse:
        total = self.success_count + self.failure_count
        now = time.perf_counter()
        elapsed = max(0.001, (self.end_time or now) - self.start_time) if self.start_time > 0 else 0.001

        rps = round(total / elapsed, 1)
        db_wps = round(self.db_writes / elapsed, 1)

        sorted_lat = sorted(self.latencies) if self.latencies else [0.0]
        n = len(sorted_lat)

        def percentile(p):
            if not sorted_lat or n == 0:
                return 0.0
            idx = int(math.ceil((p / 100.0) * n)) - 1
            return round(sorted_lat[max(0, min(idx, n - 1))], 2)

        avg_lat = round(sum(sorted_lat) / max(1, n), 2)

        return LoadTestMetricResponse(
            running=self.running,
            total_requests=total,
            success_count=self.success_count,
            failure_count=self.failure_count,
            rps=rps,
            avg_latency_ms=avg_lat,
            p50_latency_ms=percentile(50),
            p90_latency_ms=percentile(90),
            p95_latency_ms=percentile(95),
            p99_latency_ms=percentile(99),
            db_writes_per_sec=db_wps,
            duration_sec=round(elapsed, 2),
            errors_breakdown=dict(self.errors_breakdown)
        )

    async def run(self, post_id: int, target_count: int, concurrency: int, group_tag: Optional[str] = None):
        self.reset()
        self.running = True
        self.post_id = post_id
        self.concurrency = concurrency
        self.total_target = target_count
        self.start_time = time.perf_counter()

        # Fetch test accounts
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "SELECT id, username, status FROM users WHERE username != 'admin'"
        params = []
        if group_tag:
            query += " AND group_tag = ?"
            params.append(group_tag)
        query += " ORDER BY id ASC LIMIT ?"
        params.append(target_count)

        cursor.execute(query, params)
        accounts = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not accounts:
            self.running = False
            return

        semaphore = asyncio.Semaphore(concurrency)

        async def worker(acc):
            if self.stop_requested:
                return

            async with semaphore:
                req_start = time.perf_counter()
                user_id = acc["id"]
                success = False
                err_category = None

                # Test account status check
                if acc["status"] != "ACTIVE":
                    err_category = f"Account_{acc['status']}"
                else:
                    try:
                        c = get_db_connection()
                        cur = c.cursor()

                        # Check post exists
                        cur.execute("SELECT id FROM posts WHERE id = ?", (self.post_id,))
                        if not cur.fetchone():
                            err_category = "Post_Not_Found_404"
                        else:
                            # Check duplicate like
                            cur.execute("SELECT id FROM likes WHERE post_id = ? AND user_id = ?", (self.post_id, user_id))
                            if cur.fetchone():
                                err_category = "Duplicate_Like_400"
                            else:
                                cur.execute("""
                                    INSERT INTO likes (post_id, user_id, method)
                                    VALUES (?, ?, 'API_LOADTEST')
                                """, (self.post_id, user_id))
                                cur.execute("UPDATE posts SET likes_count = likes_count + 1 WHERE id = ?", (self.post_id,))
                                c.commit()
                                success = True
                                self.db_writes += 2
                        c.close()
                    except Exception as ex:
                        err_str = str(ex).lower()
                        if "locked" in err_str:
                            err_category = "DB_Locked_Timeout"
                        elif "unique" in err_str:
                            err_category = "Duplicate_Unique_Constraint"
                        else:
                            err_category = "DB_Exception"

                duration_ms = (time.perf_counter() - req_start) * 1000.0
                self.latencies.append(duration_ms)

                if success:
                    self.success_count += 1
                else:
                    self.failure_count += 1
                    err_key = err_category or "Unknown_Failure"
                    self.errors_breakdown[err_key] = self.errors_breakdown.get(err_key, 0) + 1

        # Periodic metric broadcast task
        async def metric_broadcaster():
            while self.running:
                await asyncio.sleep(0.25)
                metrics = self.get_metrics()
                await manager.broadcast({
                    "type": "loadtest_metrics",
                    "data": metrics.model_dump()
                })

        b_task = asyncio.create_task(metric_broadcaster())

        # Launch workers
        tasks = [worker(acc) for acc in accounts]
        await asyncio.gather(*tasks, return_exceptions=True)

        self.running = False
        self.end_time = time.perf_counter()
        b_task.cancel()

        # Final broadcast
        final_metrics = self.get_metrics()
        await manager.broadcast({
            "type": "loadtest_metrics",
            "data": final_metrics.model_dump()
        })

engine = LoadTestEngine()

@router.post("/start", response_model=LoadTestMetricResponse)
async def start_load_test(req: StartLoadTestRequest, background_tasks: BackgroundTasks):
    if engine.running:
        raise HTTPException(status_code=400, detail="A load test is already actively running")

    asyncio.create_task(engine.run(
        post_id=req.post_id,
        target_count=req.account_count,
        concurrency=req.concurrency,
        group_tag=req.group_tag
    ))

    # Give brief moment to initialize
    await asyncio.sleep(0.05)
    return engine.get_metrics()

@router.post("/stop", response_model=LoadTestMetricResponse)
def stop_load_test():
    if not engine.running:
        return engine.get_metrics()
    engine.stop_requested = True
    return engine.get_metrics()

@router.get("/status", response_model=LoadTestMetricResponse)
def get_load_test_status():
    return engine.get_metrics()

@router.post("/reset-post-likes/{post_id}")
def reset_post_likes(post_id: int):
    """Utility to clear likes on a post before running fresh load tests."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM likes WHERE post_id = ?", (post_id,))
    deleted = cursor.rowcount
    cursor.execute("UPDATE posts SET likes_count = 0 WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
    return {"success": True, "cleared_likes": deleted, "post_id": post_id}
