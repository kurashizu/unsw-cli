"""Unified Azure AD SSO login for Moodle and myUNSW.

Both Moodle and myUNSW use Microsoft Azure AD SSO. While the actual
session cookies (MoodleSession, PS_TOKEN) are domain-scoped and can't
be shared, the browser-based login flow is identical. We open a single
browser window and walk the user through both logins sequentially,
capturing each session cookie as it's verified.

Usage:
    from unsw.auth.sso import sso_login_all
    success = sso_login_all(config, platforms=["moodle", "myunsw"])
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from unsw.auth.browser import (
    BrowserLoginError,
    _check_playwright,
    _ensure_chromium_installed,
)
from unsw.config import Config
from unsw.utils.output import console, print_error, print_info, print_success

# Moodle session cookie details
MOODLE_URL = "https://moodle.telt.unsw.edu.au"
MOODLE_COOKIE_NAME = "MoodleSession"

# myUNSW session details
MYUNSW_URL = "https://my.unsw.edu.au"
# myUNSW (PeopleSoft) uses these cookies:
MYUNSW_COOKIE_NAMES = {"PS_TOKEN", "PS_TOKENEXPIRE", "myunsw_session"}

# Common SSO/identity cookies that indicate Azure AD auth completed
SSO_COOKIE_NAMES = {"ESTSAUTHPERSISTENT", "SignInStateCookie", "buid"}

POLL_INTERVAL = 1.0  # seconds
TIMEOUT = 600  # 10 minutes per platform
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


async def _verify_moodle_cookie(cookie_value: str) -> bool:
    """Verify a MoodleSession cookie by making a request to /my/."""
    client = httpx.Client(
        follow_redirects=False,
        timeout=10.0,
        cookies={"MoodleSession": cookie_value},
        headers={"User-Agent": USER_AGENT},
    )
    try:
        resp = client.get(f"{MOODLE_URL}/my/")
        return not (
            resp.status_code in (302, 303, 307, 308) or "login" in str(resp.url).lower()
        )
    except Exception:
        return False


async def _verify_myunsw_session(cookies: dict[str, str]) -> bool:
    """Verify myUNSW session cookies by accessing the protected portal URL.

    The root URL returns a 200 search page even when not authenticated,
    so we use /portal/ which redirects to sso.unsw.edu.au/cas/login when
    the user is not signed in.
    """
    from unsw.auth.myunsw import _check_session_cookies

    return _check_session_cookies(cookies)


async def _wait_for_moodle_login(context) -> Optional[str]:
    """Wait for user to complete Moodle SSO, return the verified cookie value."""
    print_info("  1. Wait for the Moodle (or Microsoft login) page to load")
    print_info("  2. Log in with your UNSW zID and password")
    print_info("  3. If prompted, complete MFA")
    print_info("  4. After logging in, you should see the Moodle dashboard")
    print_info("")

    start_time = time.time()
    pending_cookie = None
    cookie_value: Optional[str] = None

    while time.time() - start_time < TIMEOUT:
        try:
            cookies = await context.cookies()
            for c in cookies:
                if c["name"] == MOODLE_COOKIE_NAME and c.get("value"):
                    pending_cookie = c["value"]
                    break
        except Exception:
            pass

        if pending_cookie:
            if await _verify_moodle_cookie(pending_cookie):
                cookie_value = pending_cookie
                print_info("  ✅ MoodleSession cookie verified!")
                return cookie_value
            else:
                if cookie_value is None:
                    cookie_value = ""
                    print_info("  ⏳ Waiting for Moodle login to complete...")

        await asyncio.sleep(POLL_INTERVAL)

    print_info(f"  ⏱  Timeout ({TIMEOUT // 60} min) reached.")
    return None


async def _wait_for_myunsw_login(context, page) -> Optional[dict[str, str]]:
    """Wait for user to complete myUNSW SSO, return the verified session cookies.

    Strategy: navigate the browser to /portal/ and check whether we end up
    on the dashboard (not on a CAS or Microsoft login page). The browser
    carries all SSO cookies automatically, so this works reliably across
    the multi-domain auth chain.
    """
    print_info("  1. Wait for the myUNSW page to load")
    print_info("  2. Log in with your UNSW zID and password (Azure AD SSO)")
    print_info("  3. If prompted, complete MFA")
    print_info("  4. After logging in, you should see the myUNSW Student Portal")
    print_info("")

    start_time = time.time()
    captured = None
    poll_count = 0

    while time.time() - start_time < TIMEOUT:
        poll_count += 1
        try:
            # Navigate the browser to /portal/ — this carries all the
            # SSO cookies across domains automatically. If the user is
            # logged in, we'll land on the dashboard (200).
            await page.goto(
                f"{MYUNSW_URL}/portal/",
                wait_until="domcontentloaded",
                timeout=10000,
            )
            current_url = page.url.lower()
            page_title = (await page.title()).lower()

            # If we're on the dashboard, we have a session
            is_dashboard = (
                "login" not in current_url
                and "sso.unsw.edu.au" not in current_url
                and "microsoftonline" not in current_url
                and "sign in" not in page_title
                and "log in" not in page_title
            )

            if is_dashboard:
                # Capture all cookies now that we know the session is valid
                all_cookies = await context.cookies()
                cookies = {}
                for c in all_cookies:
                    domain = c.get("domain", "")
                    name = c["name"]
                    value = c.get("value", "")
                    if not value:
                        continue
                    # Include myUNSW and SSO cookies
                    if (
                        "my.unsw.edu.au" in domain
                        or "unsw.edu.au" in domain
                        or "microsoftonline" in domain
                        or name in MYUNSW_COOKIE_NAMES
                        or name in SSO_COOKIE_NAMES
                    ):
                        cookies[name] = value

                captured = cookies
                print_info("  ✅ myUNSW session verified!")
                return captured

            # Show waiting message once
            if captured is None:
                captured = {}  # Mark message shown
                print_info("  ⏳ Waiting for myUNSW login to complete...")

            # Heartbeat every 30s
            if poll_count % 30 == 0:
                elapsed = int(time.time() - start_time)
                print_info(f"  Still waiting... ({elapsed}s elapsed)")

        except Exception as e:
            # Navigation can fail while SSO is redirecting — that's OK
            # print_info(f"  (Navigation: {e})")
            pass

        await asyncio.sleep(POLL_INTERVAL)

    print_info(f"  ⏱  Timeout ({TIMEOUT // 60} min) reached.")
    return None


async def _sso_login_flow(config: Config, platforms: list[str]) -> dict[str, bool]:
    """Open browser once, log into each platform in sequence.

    Args:
        config: User config for cookie persistence
        platforms: List of platforms to log into ("moodle", "myunsw")

    Returns:
        Dict mapping platform name to success bool.
    """
    from playwright.async_api import async_playwright

    print_info("Opening browser for UNSW SSO login...")
    print_info("  You'll log into Moodle and myUNSW in one session.")
    print_info("  The browser stays open — just complete each login in turn.")
    print_info(f"  Timeout: {TIMEOUT // 60} minutes per platform\n")

    results: dict[str, bool] = {p: False for p in platforms}

    async with async_playwright() as p:
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
            return results

        try:
            context = await browser.new_context(
                viewport={"width": 1024, "height": 768},
                user_agent=USER_AGENT,
                no_viewport=True,
            )
            page = await context.new_page()
        except Exception as e:
            print_error(f"Failed to create browser page: {e}")
            await browser.close()
            return results

        try:
            # ── Moodle ─────────────────────────────────────────
            if "moodle" in platforms:
                print_info("\n📚 Moodle login")
                print_info(f"  Navigating to {MOODLE_URL}...")
                try:
                    await page.goto(MOODLE_URL, wait_until="commit", timeout=30000)
                except Exception as e:
                    print_info(f"  (Navigation note: {e})")

                cookie = await _wait_for_moodle_login(context)
                if cookie:
                    cookies_dict = config.load_cookies()
                    cookies_dict[MOODLE_COOKIE_NAME] = cookie
                    config.save_cookies(cookies_dict)
                    print_success("✓ MoodleSession captured and saved!")
                    results["moodle"] = True
                else:
                    print_warning("✗ Moodle login did not complete.")

            # ── myUNSW ─────────────────────────────────────────
            if "myunsw" in platforms:
                print_info("\n🎓 myUNSW login")
                print_info(f"  Navigating to {MYUNSW_URL}...")
                try:
                    await page.goto(MYUNSW_URL, wait_until="commit", timeout=30000)
                except Exception as e:
                    print_info(f"  (Navigation note: {e})")

                session_cookies = await _wait_for_myunsw_login(context, page)
                if session_cookies:
                    # Save with myunsw_ prefix to namespace them
                    all_cookies = config.load_cookies()
                    for k, v in session_cookies.items():
                        all_cookies[f"myunsw_{k}"] = v
                    config.save_cookies(all_cookies)
                    print_success("✓ myUNSW session captured and saved!")
                    results["myunsw"] = True
                else:
                    print_warning("✗ myUNSW login did not complete.")

        finally:
            print_info("\n  Closing browser...")
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass

    return results


def sso_login_all(
    config: Config, platforms: list[str] | None = None
) -> dict[str, bool]:
    """Open browser once and log into multiple SSO-required platforms.

    Args:
        config: User config for cookie persistence
        platforms: List of platforms to log into. Defaults to ["moodle", "myunsw"].

    Returns:
        Dict mapping platform name to success bool. Empty dict if Playwright
        or Chromium is missing.
    """
    if platforms is None:
        platforms = ["moodle", "myunsw"]

    # Validate platforms
    valid = {"moodle", "myunsw"}
    platforms = [p for p in platforms if p in valid]
    if not platforms:
        print_error("No valid SSO platforms specified.")
        return {}

    # Check prerequisites
    try:
        _check_playwright()
        _ensure_chromium_installed()
    except BrowserLoginError as e:
        print_error(str(e))
        return {}

    try:
        return asyncio.run(_sso_login_flow(config, platforms))
    except KeyboardInterrupt:
        print_info("\nLogin cancelled.")
        return {p: False for p in platforms}
    except Exception as e:
        print_error(f"Browser login failed: {e}")
        import traceback

        print_info(f"  Details: {traceback.format_exc()}")
        return {p: False for p in platforms}
