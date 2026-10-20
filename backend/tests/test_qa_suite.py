import pytest
import time
import asyncio
import uuid
import sys
import os
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.main import app
from app.database import init_db, get_db_connection
from app.middleware.rate_limiter import global_rate_limiter

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_qa_env():
    init_db()
    global_rate_limiter.clear()
    global_rate_limiter.enabled = True
    global_rate_limiter.requests_per_minute = 120
    yield

class TestQualityAssuranceSuite:
    """
    Exhaustive QA Test Suite covering architecture, edge cases,
    scale, concurrency, security boundaries and data integrity.
    """

    def test_qa_01_mass_account_generation_performance(self):
        """QA-01: Scale Test - Batch insert 1,000 accounts under 2 seconds."""
        t0 = time.perf_counter()
        res = client.post("/api/accounts/generate", json={
            "count": 1000,
            "group_tag": "qa_scale_1000",
            "prefix": "qa_bot",
            "pre_generate_sessions": True
        })
        elapsed = time.perf_counter() - t0

        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.json()
        assert data["created_count"] == 1000
        assert elapsed < 3.0, f"Account generation took {elapsed}s, expected < 3.0s"

        # Verify DB consistency
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM users WHERE group_tag = 'qa_scale_1000'")
        count = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) as s_cnt FROM sessions WHERE is_active = 1")
        session_count = cur.fetchone()["s_cnt"]
        conn.close()

        assert count == 1000
        assert session_count >= 1000

    def test_qa_02_duplicate_like_atomic_constraint(self):
        """QA-02: Integrity Test - Ensure no user can like the same post twice."""
        # 1. Login user
        login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Clear existing likes on post 1
        client.post("/api/loadtest/reset-post-likes/1")

        # 2. First like should succeed
        res1 = client.post("/api/posts/1/like", headers=headers)
        assert res1.status_code == 200
        assert res1.json()["action"] == "liked"

        # 3. Second like must be rejected with HTTP 400
        res2 = client.post("/api/posts/1/like", headers=headers)
        assert res2.status_code == 400
        assert "already liked" in res2.json()["detail"].lower()

        # 4. Verify post likes_count is exactly 1, not 2
        post = client.get("/api/posts/1", headers=headers).json()
        assert post["likes_count"] == 1

    def test_qa_03_session_expiration_and_tampering(self):
        """QA-03: Security & Session Test - Expired, malformed and forged tokens."""
        # Case A: Malformed Token
        res_malformed = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid_token_12345"})
        assert res_malformed.status_code == 401
        assert "validation failed" in res_malformed.json()["detail"].lower()

        # Case B: Expired Token
        reg = client.post("/api/auth/register", json={
            "username": f"qa_expire_{uuid.uuid4().hex[:6]}",
            "password": "password123"
        })
        token = reg.json()["token"]

        # Expire token
        client.post("/api/auth/expire-session", json={"token": token})

        res_expired = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res_expired.status_code == 401
        assert "expired" in res_expired.json()["detail"].lower()

        # Case C: Disabled User Token
        reg_dis = client.post("/api/auth/register", json={
            "username": f"qa_disabled_{uuid.uuid4().hex[:6]}",
            "password": "password123"
        })
        dis_uid = reg_dis.json()["user"]["id"]
        dis_token = reg_dis.json()["token"]

        # Disable user
        client.post("/api/accounts/bulk-action", json={
            "account_ids": [dis_uid],
            "action": "disable"
        })

        res_disabled = client.get("/api/auth/me", headers={"Authorization": f"Bearer {dis_token}"})
        assert res_disabled.status_code == 401
        assert "disabled" in res_disabled.json()["detail"].lower()

    def test_qa_04_rate_limiting_sliding_window(self):
        """QA-04: Throttling Test - Strict sliding window rate limiting."""
        # Configure strict limit of 3 req/min
        client.post("/api/config/rate-limit?enabled=true&requests_per_minute=3")

        login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        status_codes = []
        for _ in range(6):
            res = client.post("/api/posts/1/like", headers=headers)
            status_codes.append(res.status_code)

        assert 429 in status_codes, f"Expected 429 Too Many Requests in {status_codes}"

        # Reset rate limit to standard
        client.post("/api/config/rate-limit?enabled=true&requests_per_minute=120")

    def test_qa_05_network_inspector_seven_layer_trace(self):
        """QA-05: Inspector Audit - Full 7-layer lifecycle verification."""
        login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Clear likes on post 2 and like it
        client.post("/api/loadtest/reset-post-likes/2")
        client.post("/api/posts/2/like?method=QA_INSPECTOR", headers=headers)

        # Retrieve inspector trace
        logs_res = client.get("/api/inspector/logs?limit=1")
        assert logs_res.status_code == 200
        latest_log = logs_res.json()["items"][0]

        detail_res = client.get(f"/api/inspector/logs/{latest_log['id']}")
        assert detail_res.status_code == 200
        trace = detail_res.json()

        # Verify sensitive credentials masked
        req_headers = trace["request_headers"]
        auth_header = req_headers.get("authorization", "")
        assert "****" in auth_header, f"Authorization header was not masked: {auth_header}"

        # Verify all 7 lifecycle stages
        stages = trace["lifecycle_stages"]
        assert len(stages) == 7

        stage_names = [s["name"] for s in stages]
        expected_names = [
            "瀏覽器 / 客戶端 (Browser / Client)",
            "HTTP 請求傳輸 (HTTP Request)",
            "FastAPI 路由引擎 (FastAPI Engine)",
            "Session 憑證驗證 (Session Validation)",
            "SQLite 原子交易 (SQLite Transaction)",
            "HTTP 回應封裝 (HTTP Response)",
            "UI 更新與即時廣播 (UI Update & Broadcast)"
        ]
        assert stage_names == expected_names

        # Layer 4 (Session Validation) verdict
        assert stages[3]["status"] == "VALID"
        assert stages[3]["data"]["username"] == "admin"

        # Layer 5 (SQLite Transaction) delta
        assert stages[4]["status"] == "COMMITTED"
        assert stages[4]["data"]["action"] == "INSERT_LIKE_INCREMENT_COUNT"

    def test_qa_06_load_test_engine_throughput(self):
        """QA-06: Stress Engine - Verify async benchmark metrics collection."""
        # Ensure at least 100 accounts exist
        client.post("/api/accounts/generate", json={
            "count": 100,
            "group_tag": "qa_bench_pool",
            "prefix": "qa_bench"
        })

        client.post("/api/loadtest/reset-post-likes/3")

        # Start 50-account load test
        start_res = client.post("/api/loadtest/start", json={
            "post_id": 3,
            "account_count": 50,
            "concurrency": 10,
            "group_tag": "qa_bench_pool"
        })
        assert start_res.status_code == 200

        # Wait for completion
        time.sleep(1.0)
        status_res = client.get("/api/loadtest/status")
        assert status_res.status_code == 200
        metrics = status_res.json()

        assert metrics["total_requests"] >= 10
        assert metrics["rps"] > 0
        assert metrics["avg_latency_ms"] >= 0
        assert "p95_latency_ms" in metrics
        assert "p99_latency_ms" in metrics
        assert "db_writes_per_sec" in metrics

    def test_qa_07_bulk_account_management_lifecycle(self):
        """QA-07: Account Lifecycle - Enable -> Disable -> Expire -> Delete."""
        # Generate 20 test accounts
        tag = f"lifecycle_{uuid.uuid4().hex[:6]}"
        client.post("/api/accounts/generate", json={
            "count": 20,
            "group_tag": tag,
            "prefix": "life"
        })

        # 1. Disable
        dis_res = client.post("/api/accounts/bulk-action", json={"group_tag": tag, "action": "disable"})
        assert dis_res.json()["affected_rows"] == 20

        # 2. Enable
        en_res = client.post("/api/accounts/bulk-action", json={"group_tag": tag, "action": "enable"})
        assert en_res.json()["affected_rows"] == 20

        # 3. Expire Sessions
        exp_res = client.post("/api/accounts/bulk-action", json={"group_tag": tag, "action": "expire_sessions"})
        assert exp_res.json()["affected_rows"] == 20

        # 4. Delete
        del_res = client.post("/api/accounts/bulk-action", json={"group_tag": tag, "action": "delete"})
        assert del_res.json()["affected_rows"] == 20

        # Verify 0 left
        left = client.get(f"/api/accounts?group_tag={tag}").json()["total"]
        assert left == 0

    def test_qa_08_chaos_simulation(self):
        """QA-08: Chaos Injection - Test latency & error injection configuration."""
        # 1. Configure Chaos
        res = client.post("/api/config/chaos?enabled=true&delay_ms=200&fail_rate=0.5")
        assert res.status_code == 200
        cfg = res.json()["chaos"]
        assert cfg["enabled"] is True
        assert cfg["delay_ms"] == 200
        assert cfg["fail_rate"] == 0.5

        # 2. Query Chaos
        get_res = client.get("/api/config/chaos")
        assert get_res.status_code == 200
        assert get_res.json()["enabled"] is True

        # 3. Disable Chaos
        client.post("/api/config/chaos?enabled=false&delay_ms=0&fail_rate=0.0")

    def test_qa_09_account_export_formats(self):
        """QA-09: Export Audit - Verify CSV and JSON account export."""
        # Ensure accounts exist
        client.post("/api/accounts/generate", json={"count": 10, "group_tag": "qa_export_test"})

        # CSV Export
        csv_res = client.get("/api/accounts/export?format=csv&group_tag=qa_export_test")
        assert csv_res.status_code == 200
        assert "text/csv" in csv_res.headers.get("content-type", "")
        assert "id,username,display_name,status,group_tag" in csv_res.text
        assert "qa_export_test" in csv_res.text

        # JSON Export
        json_res = client.get("/api/accounts/export?format=json&group_tag=qa_export_test")
        assert json_res.status_code == 200
        assert "application/json" in json_res.headers.get("content-type", "")
        data = json_res.json()
        assert "accounts" in data
        assert isinstance(data["accounts"], list)
        assert len(data["accounts"]) >= 10
        assert data["accounts"][0]["group_tag"] == "qa_export_test"

    def test_qa_10_timing_waterfall_and_curl(self):
        """QA-10: Inspector Audit - Verify cURL command and timing waterfall."""
        login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        client.post("/api/posts/1/like", headers=headers)
        logs = client.get("/api/inspector/logs?limit=1").json()
        log_id = logs["items"][0]["id"]

        detail = client.get(f"/api/inspector/logs/{log_id}").json()
        assert "curl_command" in detail
        assert "curl -X" in detail["curl_command"]
        assert "timing_waterfall" in detail
        wf = detail["timing_waterfall"]
        assert "dns_network_ms" in wf
        assert "route_matching_ms" in wf
        assert "session_validation_ms" in wf
        assert "sqlite_transaction_ms" in wf
        assert "serialization_ms" in wf
        assert "total_ms" in wf

    def test_qa_11_screenshot_endpoint(self):
        """QA-11: Browser Automation - Verify task screenshot status query."""
        res = client.get("/api/tasks/non_existent_task/screenshot")
        assert res.status_code == 200
        assert res.json()["available"] is False

