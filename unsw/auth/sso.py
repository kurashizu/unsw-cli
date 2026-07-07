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
import json
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
# NOTE: 'buid' is intentionally excluded — it's a browser-unique ID
# that's set on first visit, before login completes.
SSO_COOKIE_NAMES = {"ESTSAUTHPERSISTENT", "SignInStateCookie"}

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

    Strategy: check the actual browser URL — wait until we're past
    the SSO login pages AND on a real (non-public) myUNSW page AND
    we have real session cookies set. We do NOT use 'buid' as an
    indicator (it's set too early, before user types anything).
    """
    print_info("  1. Wait for the myUNSW page to load")
    print_info("  2. Log in with your UNSW zID and password (Azure AD SSO)")
    print_info("  3. If prompted, complete MFA")
    print_info("  4. After logging in, you should see the Student Hub dashboard")
    print_info("")
    print_info("  Watching for session cookies (Azure AD / myUNSW)...")
    print_info("  (The browser is yours to interact with — we just watch.)\n")

    start_time = time.time()
    poll_count = 0
    showed_message = False

    # Strong auth indicators that are only set AFTER successful login:
    STRONG_SESSION_COOKIES = {
        "ESTSAUTHPERSISTENT",  # Azure AD persistent SSO
        "SignInStateCookie",  # Azure AD sign-in state
        "DISSESSIONAuthnDelegation",  # myUNSW CAS delegation JWT
        "PS_TOKEN",  # Legacy PeopleSoft session
        "PS_TOKENEXPIRE",
    }

    while time.time() - start_time < TIMEOUT:
        poll_count += 1
        try:
            # Step 1: Check we're not still on a login page
            current_url = (page.url or "").lower()
            on_login_page = any(
                fragment in current_url
                for fragment in (
                    "sso.unsw.edu.au/cas/login",
                    "login.microsoftonline.com",
                    "login.live.com",
                )
            )
            if on_login_page:
                if not showed_message:
                    showed_message = True
                    print_info("  ⏳ Waiting for you to complete the login...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Step 2: Check we're not on the public myUNSW search page
            try:
                html = await page.content()
            except Exception:
                html = ""
            is_public = (
                "Single Sign On" in html
                or "Welcome to Single Sign On" in html
                or "Apply Online" in html
                or "Future Students" in html
            )
            if is_public:
                if not showed_message:
                    showed_message = True
                    print_info("  ⏳ Waiting for you to complete the login...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Step 3: Collect cookies, look for strong session indicators
            all_cookies = await context.cookies()
            cookies = {}
            has_strong_session = False
            for c in all_cookies:
                domain = c.get("domain", "")
                name = c["name"]
                value = c.get("value", "")
                if not value:
                    continue
                cookies[name] = value
                if name in STRONG_SESSION_COOKIES:
                    has_strong_session = True

            if not has_strong_session:
                if not showed_message:
                    showed_message = True
                    print_info("  ⏳ Waiting for you to complete the login...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # All checks pass — user is logged in
            print_info("  ✅ myUNSW session detected!")

            # IMPORTANT: navigate to an /active/ URL so the server sets a
            # JSESSIONID cookie scoped to path=/active (not just /portal).
            # Without this, plain httpx requests to /active/... endpoints
            # fail because the wrong-scoped JSESSIONID is sent.
            print_info("  Establishing /active session (BSDS endpoints)...")
            try:
                await page.goto(
                    f"{MYUNSW_URL}/active/studentClassEnrol/years.xml",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                # Give the server a moment to issue the cookie
                await asyncio.sleep(1.5)
                # Re-collect cookies — should now include JSESSIONID path=/active
                all_cookies = await context.cookies()
                for c in all_cookies:
                    if c.get("value"):
                        cookies[c["name"]] = c["value"]
                print_info("  ✅ BSDS session cookie acquired")
            except Exception as e:
                print_info(f"  (Could not prime /active session: {e})")

            return cookies

        except Exception:
            pass

        # Heartbeat every 30s
        if poll_count % 30 == 0:
            elapsed = int(time.time() - start_time)
            print_info(f"  Still waiting... ({elapsed}s elapsed)")

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

            # ── myUNSW ────────────────────────────────
                    if "myunsw" in platforms:
                        print_info("\n🎓 myUNSW login")
                        # Navigate to /portal/clientredirect which kicks off the
                        # Azure AD SSO chain and presents the Sign On button.
                        print_info(f"  Navigating to {MYUNSW_URL}/portal/clientredirect ...")
                        try:
                            await page.goto(
                                f"{MYUNSW_URL}/portal/clientredirect?client_name=azuread&service=https%3A%2F%2Fmy.unsw.edu.au%2Fportal%2F",
                                wait_until="commit",
                                timeout=30000,
                            )
                        except Exception as e:
                            print_info(f"  (Navigation note: {e})")

                        session_cookies = await _wait_for_myunsw_login(context, page)
            if session_cookies:
                # Save cookies AND the full browser storage state.
                # myUNSW's DISSESSIONAuthnDelegation JWT appears to be
                # session-bound, so we need the full state to resume.
                all_cookies = config.load_cookies()
                for k, v in session_cookies.items():
                    all_cookies[f"myunsw_{k}"] = v
                config.save_cookies(all_cookies)

                # Save the entire browser state for later reuse
                try:
                    state = await context.storage_state()
                    from unsw.config import CONFIG_DIR

                    state_path = CONFIG_DIR / "myunsw_storage.json"
                    state_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(state_path, "w") as f:
                        json.dump(state, f, indent=2, default=str)
                    print_info("  ✓ myUNSW browser state saved for future sessions")
                except Exception as e:
                    print_info(f"  (Note: Could not save browser state: {e})")

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
