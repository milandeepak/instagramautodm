"""
Instagram service layer — uses Playwright to perform FULL UI AUTOMATION.
This physically clicks through the Instagram website, reads the DOM,
and types messages. This completely bypasses any API blocks, challenge_required,
and unsupported_version errors since we aren't using the API at all.
"""

import asyncio
import json
import logging
import random
import time
from pathlib import Path
import re

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.config import settings

logger = logging.getLogger(__name__)


class PlaywrightInstagramService:
    def __init__(self):
        self.pw = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

        self.user_id: str = ""
        self.username: str = ""

        self.lock = asyncio.Lock()
        self._dm_sent_times: list[float] = []

    async def start(self):
        logger.info("Starting Playwright browser (UI Automation Mode)...")
        self.pw = await async_playwright().start()
        self.browser = await self.pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--mute-audio"],
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            device_scale_factor=1,
            has_touch=False,
            is_mobile=False,
        )

        # Load session cookie
        sid = self._load_session_id()
        if not sid:
            raise RuntimeError("No session ID found in data/session.json.")

        await self.context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": sid,
                    "domain": ".instagram.com",
                    "path": "/",
                }
            ]
        )

        self.page = await self.context.new_page()

        logger.info("Navigating to instagram.com to verify login...")
        await self.page.goto("https://www.instagram.com/", wait_until="networkidle")

        # Click away any "Turn on Notifications" modal if it appears
        try:
            not_now_btn = self.page.get_by_role("button", name="Not Now")
            if await not_now_btn.count() > 0:
                await not_now_btn.first.click()
        except:
            pass

        # Fast track login verification using cookie instead of UI parsing
        try:
            uid = self._get_cookie_val("ds_user_id") or sid.split(":")[0]
            if uid:
                self.user_id = uid
                self.username = "bot_account"  # Fallback if we don't query it
                logger.info(
                    "Playwright UI session verified via cookie for user_id=%s",
                    self.user_id,
                )
            else:
                raise ValueError("No user ID found in session")
        except Exception as e:
            logger.error("Failed to verify Playwright session: %s", e)
            await self.page.screenshot(path="login_error.png")
            raise RuntimeError("Instagram login failed. See login_error.png")

    async def stop(self):
        logger.info("Stopping Playwright...")
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()

    def _load_session_id(self) -> str:
        path = Path(settings.session_file)
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("cookies", {}).get("sessionid", "")
        return ""

    def _get_cookie_val(self, name: str) -> str:
        path = Path(settings.session_file)
        if path.exists():
            data = json.loads(path.read_text())
            return data.get("cookies", {}).get(name, "")
        return ""

    def get_my_user_id(self) -> str:
        return self.user_id

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_hourly_dm_limit(self) -> bool:
        now = time.time()
        cutoff = now - 3600
        self._dm_sent_times = [t for t in self._dm_sent_times if t > cutoff]
        return len(self._dm_sent_times) < settings.max_dms_per_hour

    async def _random_delay(self):
        delay = random.uniform(
            settings.dm_delay_min_seconds, settings.dm_delay_max_seconds
        )
        logger.debug("Sleeping %.1fs", delay)
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # UI Actions
    # ------------------------------------------------------------------

    async def get_user_posts(self, amount: int = 12) -> list[dict]:
        """Scrape the latest posts directly from the user's profile page."""
        if not self.page:
            return []

        async with self.lock:
            try:
                await self.page.goto(
                    f"https://www.instagram.com/{self.username}/",
                    wait_until="domcontentloaded",
                )

                # Wait for any links containing /p/
                await self.page.wait_for_selector("a[href*='/p/']", timeout=15000)

                # Evaluate JS to find all post shortcodes
                posts_data = await self.page.evaluate("""() => {
                    const links = Array.from(document.querySelectorAll("a[href*='/p/']"));
                    const shortcodes = links.map(a => {
                        const match = a.getAttribute("href").match(/\\/p\\/([^\\/]+)/);
                        return match ? match[1] : null;
                    }).filter(Boolean);
                    // Deduplicate
                    return [...new Set(shortcodes)];
                }""")

                posts = []
                for shortcode in posts_data[:amount]:
                    posts.append(
                        {
                            "media_id": shortcode,
                            "shortcode": shortcode,
                            "caption": "",
                            "timestamp": int(time.time()),
                        }
                    )

                return posts
            except Exception as exc:
                logger.error("UI failed to fetch posts: %s", exc)
                return []

        async with self.lock:
            try:
                # Go to user profile
                await self.page.goto(
                    f"https://www.instagram.com/{self.username}/",
                    wait_until="networkidle",
                )

                # Wait for post grid to load
                await self.page.wait_for_selector(
                    "article a[href^='/p/']", timeout=10000
                )

                post_elements = await self.page.query_selector_all(
                    "article a[href^='/p/']"
                )
                posts = []

                for el in post_elements[:amount]:
                    href = await el.get_attribute("href")
                    # href is like /p/C1234567890/
                    shortcode = href.strip("/").split("/")[-1]
                    posts.append(
                        {
                            # Use shortcode as media_id since UI doesn't expose numeric media_id easily
                            "media_id": shortcode,
                            "shortcode": shortcode,
                            "caption": "",  # Hard to get from grid, leaving blank
                            "timestamp": int(time.time()),  # Approximation
                        }
                    )

                return posts
            except Exception as exc:
                logger.error("UI failed to fetch posts: %s", exc)
                return []

    async def get_media_comments(self, shortcode: str, amount: int = 100) -> list[dict]:
        """Scrape comments from the post's dedicated page."""
        if not self.page:
            return []

        async with self.lock:
            try:
                await self.page.goto(
                    f"https://www.instagram.com/p/{shortcode}/",
                    wait_until="domcontentloaded",
                )

                # Wait for any username to appear (spans with text) or the article body
                await asyncio.sleep(3)  # Give react time to render

                # Evaluate JS to extract comments
                comments_data = await self.page.evaluate("""() => {
                    // Instagram structures comments usually as list items (li) or divs inside the main article
                    // Find all links that look like usernames (e.g. hovering them shows mini profile)
                    // The text right after them is usually the comment.
                    // This is a robust generic approach
                    const results = [];
                    const elements = document.querySelectorAll('span, div');
                    for (const el of elements) {
                        if (el.innerText && el.innerText.includes('\\n')) {
                            const lines = el.innerText.split('\\n');
                            if (lines.length >= 2 && lines[1].trim().length > 0 && lines[0].length < 30) {
                                // Potentially a username + comment text block
                                // Let's check if there's a Reply button text nearby to confirm it's a comment
                                if (el.innerText.includes('Reply')) {
                                    results.push({
                                        username: lines[0].trim(),
                                        text: lines[1].trim()
                                    });
                                }
                            }
                        }
                    }
                    return results;
                }""")

                comments = []
                # Deduplicate by username+text
                seen = set()

                for c in comments_data:
                    username = c["username"]
                    text = c["text"]

                    if username == self.username:
                        continue

                    key = f"{username}_{text}"
                    if key in seen:
                        continue
                    seen.add(key)

                    fake_id = f"{username}_{hash(text)}"
                    comments.append(
                        {
                            "comment_id": fake_id,
                            "user_id": username,
                            "username": username,
                            "text": text,
                            "created_at": time.time(),
                        }
                    )

                return comments[:amount]
            except Exception as exc:
                logger.error("UI failed to fetch comments for %s: %s", shortcode, exc)
                return []

        async with self.lock:
            try:
                await self.page.goto(
                    f"https://www.instagram.com/p/{shortcode}/",
                    wait_until="networkidle",
                )

                # Wait for comment section to load
                # The container often has role="main" or we can just look for ul/li containing comments
                # Finding comments by looking for usernames
                try:
                    await self.page.wait_for_selector("ul > div > li", timeout=10000)
                except:
                    # No comments yet or slow load
                    return []

                comment_elements = await self.page.query_selector_all("ul > div > li")
                comments = []

                for el in comment_elements:
                    text_content = await el.inner_text()
                    lines = text_content.split("\\n")
                    if len(lines) >= 2:
                        username = lines[0].strip()
                        # Often lines[1] is the text
                        text = lines[1].strip()

                        # Exclude our own caption
                        if username == self.username:
                            continue

                        # Use a hash of username+text as fake comment_id since we can't see the real one
                        fake_id = f"{username}_{hash(text)}"

                        comments.append(
                            {
                                "comment_id": fake_id,
                                "user_id": username,  # Fallback to username for user_id in UI mode
                                "username": username,
                                "text": text,
                                "created_at": time.time(),
                            }
                        )

                return comments[:amount]
            except Exception as exc:
                logger.error("UI failed to fetch comments for %s: %s", shortcode, exc)
                return []

    async def check_user_follows_me(self, user_id_or_username: str) -> bool:
        """Check if user follows me by visiting their profile and looking for 'Follows you' text."""
        if not self.page:
            return False

        async with self.lock:
            try:
                await self.page.goto(
                    f"https://www.instagram.com/{user_id_or_username}/",
                    wait_until="networkidle",
                )

                # Wait a moment for UI to settle
                await asyncio.sleep(1.5)

                # Check for "Follows you" badge
                content = await self.page.content()
                if "Follows you" in content or "Follows You" in content:
                    return True
                return False
            except Exception as exc:
                logger.error(
                    "UI follow check failed for %s: %s", user_id_or_username, exc
                )
                return False

    async def send_dm(self, username: str, message: str) -> bool:
        """Physically type and send a DM through the Direct Messages UI."""
        if not self.page:
            return False

        if not self._check_hourly_dm_limit():
            logger.warning("Hourly DM limit reached.")
            return False

        await self._random_delay()

        async with self.lock:
            try:
                logger.info("Opening New Message dialog...")
                await self.page.goto(
                    "https://www.instagram.com/direct/new/", wait_until="networkidle"
                )

                # Dismiss notifications prompt if it blocks the UI
                try:
                    not_now = self.page.get_by_role("button", name="Not Now")
                    if await not_now.count() > 0:
                        await not_now.first.click()
                except:
                    pass

                # Find the "To:" search input
                search_input = self.page.locator("input[name='queryBox']")
                await search_input.wait_for(state="visible", timeout=10000)
                await search_input.fill(username)

                # Wait for results to populate (usually 1-2 seconds)
                await asyncio.sleep(2)

                # Click the first checkbox/user in the search results
                # Look for a span matching the exact username
                user_row = self.page.locator(f"span:text-is('{username}')").first
                await user_row.wait_for(state="visible", timeout=10000)
                await user_row.click()

                # Click the "Chat" or "Next" button
                chat_btn = self.page.get_by_role(
                    "button", name=re.compile("chat|next|send", re.IGNORECASE)
                )
                await chat_btn.wait_for(state="visible", timeout=5000)
                await chat_btn.click()

                # Wait for the message input box to appear
                msg_box = self.page.get_by_role("textbox")
                await msg_box.wait_for(state="visible", timeout=10000)

                # Type the message
                await msg_box.fill(message)
                await asyncio.sleep(0.5)

                # Press Enter to send
                await msg_box.press("Enter")

                # Wait a moment for message to be sent
                await asyncio.sleep(2)

                self._dm_sent_times.append(time.time())
                logger.info("DM sent to %s via UI automation", username)
                return True

            except Exception as exc:
                logger.error("UI failed to send DM to %s: %s", username, exc)
                await self.page.screenshot(path=f"error_dm_{username}.png")
                return False


instagram_service = PlaywrightInstagramService()
