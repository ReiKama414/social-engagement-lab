import pytest
import asyncio
import os
import sys
import uvicorn
import multiprocessing
import time
from playwright.async_api import async_playwright

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.database import init_db, get_db_connection

def run_server():
    from app.main import app
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")

@pytest.fixture(scope="module")
def server():
    init_db()
    proc = multiprocessing.Process(target=run_server, daemon=True)
    proc.start()
    time.sleep(1.2) # wait for uvicorn to bind
    yield "http://127.0.0.1:8001"
    proc.terminate()

@pytest.mark.asyncio
async def test_playwright_e2e_social_flow(server):
    base_url = server
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context()
        page = await context.new_page()

        # 1. Open mock social page
        await page.goto(f"{base_url}/mock-social", wait_until="domcontentloaded")
        assert "Lab Sandbox" in await page.title()

        # 2. Click login button to open modal
        login_btn = page.locator("#authBtn")
        await login_btn.click()

        # 3. Enter credentials and submit
        await page.fill("#username", "admin")
        await page.fill("#password", "password123")
        await page.click("#submitLogin")

        # 4. Wait for auth status to show @admin
        await page.wait_for_selector("text=@admin", timeout=5000)

        # Ensure post 1 is not pre-liked by admin
        conn = get_db_connection()
        conn.execute("DELETE FROM likes WHERE post_id = 1 AND user_id = 1")
        conn.commit()
        conn.close()

        # 5. Like post #1 with HTTP response interception
        async with page.expect_response(lambda r: "/api/posts/1/like" in r.url, timeout=5000) as response_info:
            like_button = page.locator("[data-like-btn='1']").first
            await like_button.click()
            response = await response_info.value
            assert response.status == 200
            data = await response.json()
            assert data["success"] is True

        # 6. Verify SQLite direct record
        await page.wait_for_timeout(300)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM likes WHERE post_id = 1 AND user_id = 1")
        like_row = cur.fetchone()
        conn.close()

        assert like_row is not None
        assert like_row["post_id"] == 1
        assert like_row["user_id"] == 1

        # 7. Close browser context
        await context.close()
        await browser.close()
