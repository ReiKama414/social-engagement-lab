import asyncio
import time
from typing import Optional, Dict, Any, Callable
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from app.database import get_db_connection

class PlaywrightWorker:
    def __init__(self, base_url: str = "http://localhost:3000", headless: bool = True):
        self.base_url = base_url.rstrip("/")
        self.headless = headless
        self.playwright = None
        self.browser: Optional[Browser] = None

    async def start(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

    async def stop(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def execute_like_flow(
        self,
        username: str,
        password: str,
        post_id: int,
        task_id: str,
        token: Optional[str] = None,
        target_url: Optional[str] = None,
        capture_screenshot: bool = False,
        on_frame_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Executes the 8-step browser automation like flow:
        1. Create isolated browser context
        2. Pre-authenticate with session token if available
        3. Open social login / feed page
        4. Authenticate via UI modal if needed
        5. Locate target post
        6. Click like button & intercept API response
        7. Query SQLite database to verify like persisted
        8. Capture live screenshot & close context
        """
        start_time = time.perf_counter()
        if not self.browser:
            await self.start()

        context: BrowserContext = await self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=f"Playwright-Bot/{username}"
        )

        # Pre-authenticate via localStorage init script if token provided
        if token:
            await context.add_init_script(f"""
                localStorage.setItem('social_lab_token', '{token}');
                localStorage.setItem('social_lab_user', JSON.stringify({{ username: '{username}' }}));
            """)

        page: Page = await context.new_page()

        page_url = target_url or (f"{self.base_url}/mock-social" if "8000" in self.base_url else f"{self.base_url}/feed")

        api_response_received = False
        api_status = None
        error_msg = None

        try:
            # Step 1 & 2: Navigate to page
            await page.goto(page_url, timeout=10000, wait_until="domcontentloaded")
            await page.wait_for_timeout(250)

            if on_frame_callback:
                try:
                    import base64
                    s_bytes = await page.screenshot(type="jpeg", quality=45)
                    b64 = f"data:image/jpeg;base64,{base64.b64encode(s_bytes).decode('utf-8')}"
                    await on_frame_callback(b64, "正在載入動態牆並鎖定貼文")
                except Exception:
                    pass

            # Step 3: Login if not already logged in
            auth_trigger = page.locator("#authBtn, button:has-text('登入'), button:has-text('Log In')").first
            if not token and await auth_trigger.count() > 0 and await auth_trigger.is_visible():
                await auth_trigger.click()
                await page.wait_for_timeout(250)

                user_input = page.locator("#loginModal #username, input[name='username']").first
                if await user_input.count() > 0 and await user_input.is_visible():
                    await user_input.fill(username)
                    pwd_input = page.locator("#loginModal #password, input[name='password']").first
                    await pwd_input.fill(password)
                    submit_btn = page.locator("#loginModal #submitLogin, form button[type='submit']").first
                    await submit_btn.click()
                    await page.wait_for_timeout(600)

            # Step 4: Locate target post
            post_card = page.locator(f"[data-post-id='{post_id}']").first
            if await post_card.count() == 0:
                await page.wait_for_timeout(400)

            # Step 5 & 6: Set up response listener and click like button
            like_button = page.locator(f"[data-post-id='{post_id}'] button[data-action='like'], button[data-like-btn='{post_id}']").first
            if await like_button.count() == 0:
                like_button = page.locator(f"button[data-like-btn='{post_id}']").first
            if await like_button.count() == 0:
                like_button = page.locator(f"button[aria-label*='Like'], button:has-text('Like')").first

            # Intercept response
            async with page.expect_response(
                lambda response: f"/api/posts/{post_id}/like" in response.url or f"/api/posts/{post_id}/unlike" in response.url,
                timeout=6000
            ) as response_info:
                await like_button.click()
                resp = await response_info.value
                api_status = resp.status
                api_response_received = (api_status == 200)

            # Step 7: Verify directly in SQLite
            await page.wait_for_timeout(150)

            # Frame callback right after like
            screenshot_b64 = None
            if on_frame_callback or capture_screenshot:
                try:
                    import base64
                    s_bytes = await page.screenshot(type="jpeg", quality=45)
                    screenshot_b64 = f"data:image/jpeg;base64,{base64.b64encode(s_bytes).decode('utf-8')}"
                    if on_frame_callback:
                        await on_frame_callback(screenshot_b64, f"已點擊貼文 #{post_id} 愛心按讚")
                except Exception:
                    pass

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT l.id
                FROM likes l
                JOIN users u ON l.user_id = u.id
                WHERE l.post_id = ? AND u.username = ?
            """, (post_id, username))
            db_record = cursor.fetchone()
            conn.close()

            db_verified = (db_record is not None)

            # Optional Screenshot Capture
            screenshot_b64 = None
            if capture_screenshot:
                try:
                    import base64
                    s_bytes = await page.screenshot(type="jpeg", quality=45)
                    screenshot_b64 = f"data:image/jpeg;base64,{base64.b64encode(s_bytes).decode('utf-8')}"
                except Exception:
                    pass

            duration = round((time.perf_counter() - start_time) * 1000, 2)

            return {
                "success": api_response_received,
                "username": username,
                "post_id": post_id,
                "api_status": api_status,
                "db_verified": db_verified,
                "duration_ms": duration,
                "screenshot": screenshot_b64,
                "error": None if api_response_received else f"HTTP {api_status}: Action failed (Simulated Chaos or Server Error)"
            }

        except Exception as e:
            duration = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "success": False,
                "username": username,
                "post_id": post_id,
                "api_status": api_status,
                "db_verified": False,
                "duration_ms": duration,
                "screenshot": None,
                "error": str(e)
            }
        finally:
            # Step 8: Close context
            await context.close()
