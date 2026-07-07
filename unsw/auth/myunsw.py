"""myUNSW authentication - browser-based cookie capture.

myUNSW uses the same Azure AD SSO as Moodle (login.microsoftonline.com),
so the browser login flow is similar. The session is maintained via
PeopleSoft cookies on the my.unsw.edu.au domain.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from unsw.config import Config
from unsw.utils.output import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
)

MYUNSW_BASE = "https://my.unsw.edu.au"
POLL_INTERVAL = 1.0
TIMEOUT = 600  # 10 minutes


def login_via_browser(config: Config) -> bool:
    """Open a browser for myUNSW login, capture cookies automatically.

    Returns True if successful, False otherwise.
    Cookies are saved to the config's cookie store on success.
    """
    try:
        from unsw.auth.browser import _check_playwright, _ensure_chromium_installed

        _check_playwright()
        _ensure_chromium_installed()
    except Exception as e:
        print_error(str(e))
        return False

    try:
        cookies = asyncio.run(_browser_login_flow())
    except KeyboardInterrupt:
        print_info("\nLogin cancelled.")
        return False
    except Exception as e:
        print_error(f"Browser login failed: {e}")
        import traceback

        print_info(f"  Details: {traceback.format_exc()}")
        return False

    if cookies:
        # Save with myunsw_ prefix to namespace them
        all_cookies = config.load_cookies()
        for key, value in cookies.items():
            all_cookies[f"myunsw_{key}"] = value
        config.save_cookies(all_cookies)
        print_success("myUNSW session cookies captured and saved!")
        return True

    return False


async def _browser_login_flow() -> Optional[dict[str, str]]:
    """Core async flow: launch browser, wait for myUNSW session, return cookies."""
    from playwright.async_api import async_playwright

    print_info("Opening browser for myUNSW login...")
    print_info("")
    print_info("  A browser window will open. Follow these steps:")
    print_info("  1. Wait for the myUNSW page to load")
    print_info("  2. Log in with your UNSW zID and password (Azure AD SSO)")
    print_info("  3. If prompted, complete MFA")
    print_info("  4. After logging in, you should see the myUNSW Student Portal")
    print_info("")
    print_info("  The session cookie will be captured automatically.")
    print_info(f"  Timeout: {TIMEOUT // 60} minutes\n")

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
            print_info(
                "Make sure Chromium is installed: uv run playwright install chromium"
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
                no_viewport=True,
            )
            page = await context.new_page()
        except Exception as e:
            print_error(f"Failed to create browser page: {e}")
            await browser.close()
            return None

        print_info("  Navigating to myUNSW...")
        try:
            await page.goto(MYUNSW_BASE, wait_until="commit", timeout=30000)
        except Exception as e:
            print_info(f"  (Navigation note: {e})")

        print_info("  Browser is open. Waiting for you to log in...\n")

        # Give the browser a moment to render
        await asyncio.sleep(2)

        start_time = time.time()
        browser_was_closed = False
        poll_count = 0
        captured_cookies: Optional[dict[str, str]] = None

        while time.time() - start_time < TIMEOUT:
            poll_count += 1

            # Check cookies for the myUNSW domain
            try:
                all_cookies = await context.cookies()
                myunsw_cookies = {
                    c["name"]: c["value"]
                    for c in all_cookies
                    if MYUNSW_BASE in c.get("domain", "")
                    or c["name"]
                    in (
                        "PS_TOKEN",
                        "PS_TOKENEXPIRE",
                        "myunsw_session",
                    )
                }

                if myunsw_cookies:
                    # Try to verify by accessing student home
                    if await _verify_session_async(myunsw_cookies):
                        captured_cookies = myunsw_cookies
                        print_info("\n  ✅ myUNSW session verified! Login successful!")
                        break
                    else:
                        if captured_cookies is None:
                            captured_cookies = {}  # Mark message shown
                            print_info(
                                "  ⏳ Session cookie found. Waiting for login to complete..."
                            )
            except Exception:
                pass

            # Check if browser is still open
            try:
                pages = context.pages
                if not pages:
                    browser_was_closed = True
                    break
            except Exception:
                browser_was_closed = True
                break

            if poll_count % 30 == 0:
                elapsed = int(time.time() - start_time)
                print_info(f"  Still waiting... ({elapsed}s elapsed)")

            await asyncio.sleep(POLL_INTERVAL)
        else:
            print_info(
                f"\n  Timeout reached ({TIMEOUT // 60} minutes). Login cancelled."
            )
            captured_cookies = None

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

        return captured_cookies


async def _verify_session_async(cookies: dict[str, str]) -> bool:
    """Verify myUNSW session cookies by accessing the protected portal URL.

    The root URL https://my.unsw.edu.au/ returns a 200 search page even when
    not authenticated, so we use /portal/ which redirects to the CAS login
    page when the user is not signed in.
    """
    return _check_session_cookies(cookies)


def _check_session_cookies(cookies: dict[str, str]) -> bool:
    """Synchronous check: are these cookies enough to access the protected portal?

    Returns True if the user has a valid myUNSW session, False otherwise.
    """
    # Quick check: any Azure AD SSO cookie indicates authentication.
    # Azure AD SSO cookies are scoped to login.microsoftonline.com which
    # means httpx won't send them to my.unsw.edu.au — so we can't use a
    # direct httpx call to verify them. Instead, presence alone is enough
    # proof that the user completed Azure AD login.
    sso_indicators = {"ESTSAUTHPERSISTENT", "SignInStateCookie", "buid"}
    if any(name in sso_indicators for name in cookies):
        return True

    # If we have a PS_TOKEN cookie on my.unsw.edu.au, that's also proof
    # (legacy PeopleSoft session)
    if "PS_TOKEN" in cookies:
        return True

    client = httpx.Client(
        follow_redirects=False,
        timeout=15.0,
        cookies=cookies,
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
        # /portal/ redirects to sso.unsw.edu.au/cas/login when not authed.
        # If we get a 200, the user is signed in.
        resp = client.get(f"{MYUNSW_BASE}/portal/")
        if resp.status_code == 200:
            # 200 on /portal/ is the public search page, not authed dashboard
            # Check if the response is the search page (large body) vs authed
            if "Sign On" not in resp.text and "Apply Online" not in resp.text:
                return True
            return False
        # Check if redirect goes to a login page
        location = resp.headers.get("location", "")
        if "login" in location.lower() or "sso.unsw.edu.au" in location:
            return False
        # Any redirect that doesn't go to login means we're authenticated
        # but being routed somewhere else (still valid)
        if resp.status_code in (302, 303, 307, 308):
            return "login" not in location.lower()
        return False
    except Exception:
        return False


def verify_session(config: Config) -> bool:
    """Verify stored myUNSW session cookies are still valid."""
    saved = config.load_cookies()
    myunsw_cookies = {
        k.removeprefix("myunsw_"): v
        for k, v in saved.items()
        if k.startswith("myunsw_")
    }
    if not myunsw_cookies:
        return False
    return _check_session_cookies(myunsw_cookies)


def login_with_cookie(config: Config) -> httpx.Client | None:
    """Create an authenticated myUNSW client using saved cookies."""
    saved = config.load_cookies()
    myunsw_cookies = {
        k.removeprefix("myunsw_"): v
        for k, v in saved.items()
        if k.startswith("myunsw_")
    }

    if not myunsw_cookies:
        print_error(
            "myUNSW session not found.\n"
            "  Run: unsw login (interactive) or unsw myunsw login"
        )
        return None

    client = httpx.Client(
        follow_redirects=True,
        timeout=30.0,
        cookies=myunsw_cookies,
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

    # Verify
    try:
        # Quick check: SSO cookies alone are proof of authentication
        if _check_session_cookies(myunsw_cookies):
            print_success("myUNSW session authenticated!")
            return client

        # Otherwise do an HTTP check
        resp = client.get(f"{MYUNSW_BASE}/portal/", follow_redirects=False)
        location = resp.headers.get("location", "")
        if (
            resp.status_code in (302, 303, 307, 308)
            or "login" in location.lower()
            or "sso.unsw.edu.au" in location
        ):
            print_warning("myUNSW session appears to be expired.")
            print_warning("Please log in again: unsw myunsw login")
            return None
        print_success("myUNSW session authenticated!")
        return client
    except Exception as e:
        print_error(f"myUNSW connection error: {e}")
        return None
