import pytest
import os
import sys
from fastapi.testclient import TestClient

# Add backend directory to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.main import app
from app.database import init_db, get_db_connection
from app.middleware.rate_limiter import global_rate_limiter

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    init_db()
    conn = get_db_connection()
    # Clean only temporary test users, preserving creators and admin
    conn.execute("DELETE FROM users WHERE group_tag NOT IN ('admin', 'creators', 'fleet-alpha', 'community')")
    conn.execute("DELETE FROM likes WHERE task_id != 'seed-history'")
    conn.commit()
    conn.close()
    global_rate_limiter.clear()
    global_rate_limiter.enabled = True
    yield

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_admin_login():
    response = client.post("/api/auth/login", json={
        "username": "admin",
        "password": "password123"
    })
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    assert data["user"]["username"] == "admin"
    assert data["token"].startswith("sess_")

def test_user_registration_and_auth():
    reg_res = client.post("/api/auth/register", json={
        "username": "test_researcher_1",
        "password": "securepassword",
        "display_name": "Test Researcher"
    })
    assert reg_res.status_code == 200
    token = reg_res.json()["token"]

    # Verify /api/auth/me
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["username"] == "test_researcher_1"

def test_posts_and_like_flow():
    # 1. Login admin
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    token = login_res.json()["token"]

    # 2. Get posts feed
    feed_res = client.get("/api/posts", headers={"Authorization": f"Bearer {token}"})
    assert feed_res.status_code == 200
    posts = feed_res.json()
    assert len(posts) >= 1
    post_id = posts[0]["id"]
    initial_likes = posts[0]["likes_count"]

    # Ensure unliked first
    client.post(f"/api/posts/{post_id}/unlike", headers={"Authorization": f"Bearer {token}"})

    # 3. Like post
    like_res = client.post(f"/api/posts/{post_id}/like", headers={"Authorization": f"Bearer {token}"})
    assert like_res.status_code == 200
    like_data = like_res.json()
    assert like_data["success"] is True
    assert like_data["action"] == "liked"

    # 4. Duplicate like should be rejected with 400
    dup_res = client.post(f"/api/posts/{post_id}/like", headers={"Authorization": f"Bearer {token}"})
    assert dup_res.status_code == 400
    assert "already liked" in dup_res.json()["detail"].lower()

    # 5. Unlike post
    unlike_res = client.post(f"/api/posts/{post_id}/unlike", headers={"Authorization": f"Bearer {token}"})
    assert unlike_res.status_code == 200
    assert unlike_res.json()["action"] == "unliked"

def test_batch_account_generation_and_actions():
    # Generate 50 accounts
    gen_res = client.post("/api/accounts/generate", json={
        "count": 50,
        "group_tag": "pytest_fleet",
        "prefix": "pytest_bot",
        "pre_generate_sessions": True
    })
    assert gen_res.status_code == 200
    data = gen_res.json()
    assert data["success"] is True
    assert data["created_count"] == 50

    # Query accounts list
    list_res = client.get("/api/accounts?group_tag=pytest_fleet&limit=10")
    assert list_res.status_code == 200
    acc_data = list_res.json()
    assert acc_data["total"] >= 50
    assert len(acc_data["items"]) == 10
    assert acc_data["items"][0]["session_token"] is not None

    # Bulk disable accounts
    action_res = client.post("/api/accounts/bulk-action", json={
        "group_tag": "pytest_fleet",
        "action": "disable"
    })
    assert action_res.status_code == 200
    assert action_res.json()["affected_rows"] >= 50

    # Verify status changed to DISABLED
    check_res = client.get("/api/accounts?group_tag=pytest_fleet&limit=5")
    assert check_res.json()["items"][0]["status"] == "DISABLED"

def test_session_expiration_simulation():
    # Register a user
    reg = client.post("/api/auth/register", json={
        "username": "expire_tester",
        "password": "password123"
    })
    token = reg.json()["token"]

    # Verify works before expiration
    res_before = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_before.status_code == 200

    # Artificially expire the session
    client.post("/api/auth/expire-session", json={"token": token})

    # Request should now fail with 401
    res_after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res_after.status_code == 401
    assert "expired" in res_after.json()["detail"].lower()

def test_rate_limiting():
    # Set limit to 3 per minute
    client.post("/api/config/rate-limit?enabled=true&requests_per_minute=3")

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    token = login.json()["token"]

    feed_res = client.get("/api/posts", headers={"Authorization": f"Bearer {token}"})
    post_id = feed_res.json()[0]["id"]

    # Make rapid requests
    responses = []
    for _ in range(5):
        r = client.post(f"/api/posts/{post_id}/unlike", headers={"Authorization": f"Bearer {token}"})
        responses.append(r.status_code)

    # At least one should be 429
    assert 429 in responses

    # Reset rate limit
    client.post("/api/config/rate-limit?enabled=true&requests_per_minute=120")

def test_network_inspector_logging():
    # Perform an action
    login = client.post("/api/auth/login", json={"username": "admin", "password": "password123"})
    token = login.json()["token"]

    client.get("/api/posts", headers={"Authorization": f"Bearer {token}"})

    # Check inspector logs
    insp_res = client.get("/api/inspector/logs?limit=5")
    assert insp_res.status_code == 200
    logs = insp_res.json()
    assert logs["total"] >= 1
    recent_id = logs["items"][0]["id"]

    # Get single detailed log
    detail_res = client.get(f"/api/inspector/logs/{recent_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert "lifecycle_stages" in detail
    assert "Browser" in detail["lifecycle_stages"][0]["name"]
    assert "Session" in detail["lifecycle_stages"][3]["name"]
    assert "SQLite" in detail["lifecycle_stages"][4]["name"]
