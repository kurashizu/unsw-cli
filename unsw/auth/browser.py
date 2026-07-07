"""Browser-based authentication for SSO-required platforms.

Opens a Chromium window via Playwright, navigates to the platform,
waits for the user to complete SSO login, and captures the session
cookie automatically.

Both Moodle and myUNSW use Microsoft Azure AD SSO and share this same
browser-based approach.

Usage:
    from unsw.auth.browser import moodle_login_via_browser
    cookie = moodle_login_via_browser()
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

from unsw.config import CONFIG_DIR, Config
from unsw.utils.output import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

MOODLE_URL = "https://moodle.telt.unsw.edu.au"
COOKIE_NAME = "MoodleSession"
POLL_INTERVAL = 1.0  # seconds
TIMEOUT = 600  # 10 minutes max wait


class BrowserLoginError(Exception):
    """Raised when a browser-based login cannot proceed.

    This includes missing Playwright, missing Chromium browser, and
    other infrastructure-level failures (as opposed to user-level
    failures like cancelling the browser or providing bad credentials).
    """


def _check_playwright() -> None:
    """Verify Playwright is importable, with a helpful error if not."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        raise BrowserLoginError(
            "Playwright is required for browser-based login.\n"
            "  Install it with:\n"
            "    uv sync\n"
            "    uv run playwright install chromium"
        )


def _ensure_chromium_installed() -> None:
    """Best-effort check whether the Chromium binary is installed.

    If missing, raise BrowserLoginError with install instructions.
    """
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            # Try to find the chromium executable without launching it
            executable_path = p.chromium.executable_path
            import os

            if not os.path.exists(executable_path):
                raise BrowserLoginError(
                    "Chromium browser is not installed.\n"
                    "  Install it with:\n"
                    "    uv run playwright install chromium"
                )
    except BrowserLoginError:
        raise
    except Exception as e:
        # If the lookup itself fails, surface a helpful message
        raise BrowserLoginError(
            f"Could not verify Chromium installation: {e}\n"
            "  Try installing it with:\n"
            "    uv run playwright install chromium"
        )


def moodle_login_via_browser(config: Config) -> bool:
    """Open a browser for Moodle login, capture the cookie automatically.

    Returns True if successful, False otherwise (including Playwright
    missing, Chromium missing, user cancellation, or browser error).
    The cookie is saved to the config's cookie store on success.
    """
    try:
        _check_playwright()
        _ensure_chromium_installed()
    except BrowserLoginError as e:
        print_error(str(e))
        return False

    try:
        cookie = asyncio.run(_browser_login_flow())
    except KeyboardInterrupt:
        print_info("\nLogin cancelled.")
        return False
    except Exception as e:
        print_error(f"Browser login failed: {e}")
        import traceback

        print_info(f"  Details: {traceback.format_exc()}")
        return False

    if cookie:
        cookies = config.load_cookies()
        cookies[COOKIE_NAME] = cookie
        config.save_cookies(cookies)
        print_success(f"MoodleSession cookie captured and saved!")
        return True

    return False


async def _browser_login_flow() -> Optional[str]:
    """Core async flow: launch browser, wait for cookie, return it."""
    from playwright.async_api import async_playwright

    print_info("Opening browser for Moodle login...")
    print_info("")
    print_info("  A browser window will open. Follow these steps:")
    print_info("  1. Wait for the Moodle (or Microsoft login) page to load")
    print_info("  2. Log in with your UNSW zID and password")
    print_info("  3. If prompted, complete MFA (Microsoft Authenticator, SMS, etc.)")
    print_info("  4. After logging in, you should see the Moodle dashboard")
    print_info("")
    print_info("  The cookie will be captured automatically. Do NOT close the browser.")
    print_info(f"  Timeout: {TIMEOUT // 60} minutes\n")

    async with async_playwright() as p:
        # Launch browser in headed (visible) mode
        print_info("  Launching browser...")
        try:
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--window-size=1024,768",
                    "--disable-infobars",
                ],
            )
        except Exception as e:
            print_error(f"Failed to launch browser: {e}")
            print_info(
                "  If Chromium is missing, install it with:\n"
                "    uv run playwright install chromium"
            )
            return None

        try:
            context = await browser.new_context(
                viewport={"width": 1024, "height": 768},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                # Don't block any cookies
                no_viewport=True,
            )

            page = await context.new_page()
        except Exception as e:
            print_error(f"Failed to create browser page: {e}")
            await browser.close()
            return None

        cookie_value: Optional[str] = None

        # Navigate to Moodle - this will redirect to Microsoft login (SSO)
        print_info("  Navigating to Moodle...")
        try:
            # Use "commit" so we return as soon as the initial connection is made,
            # without waiting for the full SSO redirect chain to complete
            await page.goto(
                MOODLE_URL,
                wait_until="commit",
                timeout=30000,
            )
        except Exception as e:
            # Navigation might fail due to redirects - that's OK, the page is still loading
            print_info(f"  (Navigation note: {e})")

        print_info("  Browser is open. Waiting for you to log in...\n")

        # Give the browser a moment to fully render the page before polling
        await asyncio.sleep(2)

        # Wait for the MoodleSession cookie to appear
        # IMPORTANT: Moodle sets a MoodleSession cookie even before login
        # (pre-session). We must verify the cookie is actually valid by
        # making a request to the /my/ page.
        start_time = time.time()
        browser_was_closed = False
        pending_cookie = None  # Cookie value we're about to verify
        poll_count = 0

        while time.time() - start_time < TIMEOUT:
            poll_count += 1
            # Check cookies
            try:
                cookies = await context.cookies()
                for c in cookies:
                    if c["name"] == COOKIE_NAME and c.get("value"):
                        pending_cookie = c["value"]
                        break
            except Exception:
                # Context might be closed
                pass

            # If we found a cookie candidate, verify it's actually valid
            # (not just a pre-session placeholder)
            if pending_cookie:
                if await _verify_cookie_async(pending_cookie):
                    cookie_value = pending_cookie
                    print_info(
                        "\n  ✅ MoodleSession cookie verified! Login successful!"
                    )
                    break
                else:
                    # Cookie exists but is not yet authenticated
                    if cookie_value is None:
                        # Only print this once
                        cookie_value = ""  # Mark that we've shown the message
                        print_info(
                            "  ⏳ Moodle set a pre-session cookie. Waiting for you to log in..."
                        )
                    pending_cookie = None

            # Check if browser is still open
            try:
                pages = context.pages
                if not pages:
                    browser_was_closed = True
                    break
            except Exception as e:
                print_info(f"  (Browser check: {e})")
                browser_was_closed = True
                break

            # Show a heartbeat message every 30 seconds so user knows it's still waiting
            if poll_count % 30 == 0:
                elapsed = int(time.time() - start_time)
                print_info(f"  Still waiting... ({elapsed}s elapsed)")

            await asyncio.sleep(POLL_INTERVAL)
        else:
            # Timeout reached
            print_info(
                f"\n  Timeout reached ({TIMEOUT // 60} minutes). Login cancelled."
            )
            cookie_value = None

        # Cleanup
        if browser_was_closed:
            print_info("\n  Browser was closed by user.")

        try:
            await context.close()
        except Exception:
            pass
        try:
            await browser.close()
        except Exception:
            pass

        return cookie_value


async def _verify_cookie_async(cookie_value: str) -> bool:
    """Verify a MoodleSession cookie by making a request to /my/."""
    import httpx

    client = httpx.Client(
        follow_redirects=False,
        timeout=10.0,
        cookies={"MoodleSession": cookie_value},
    )
    client.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }
    )

    try:
        resp = client.get(f"{MOODLE_URL}/my/")
        # If we're redirected to a login page, the cookie is invalid
        return not (
            resp.status_code in (302, 303, 307, 308) or "login" in str(resp.url).lower()
        )
    except Exception:
        return False
