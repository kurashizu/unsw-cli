"""myUNSW authentication - browser-based cookie capture.

myUNSW uses the same Azure AD SSO as Moodle (login.microsoftonline.com),
so the browser login flow is similar. The session is maintained via
PeopleSoft cookies on the my.unsw.edu.au domain.
"""

from __future__ import annotations

import asyncio
import json
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
    """Open a browser for myUNSW login, capture cookies and storage state.

    Returns True if successful, False otherwise.
    Cookies AND full browser storage_state are saved so the session can
    be resumed in a future Playwright context.
    """
    try:
        from unsw.auth.browser import _check_playwright, _ensure_chromium_installed

        _check_playwright()
        _ensure_chromium_installed()
    except Exception as e:
        print_error(str(e))
        return False

    try:
        result = asyncio.run(_browser_login_flow_with_state())
    except KeyboardInterrupt:
        print_info("\nLogin cancelled.")
        return False
    except Exception as e:
        print_error(f"Browser login failed: {e}")
        import traceback

        print_info(f"  Details: {traceback.format_exc()}")
        return False

    if not result:
        return False

    cookies, storage_state, browser, context = result

    try:
        # Save cookies with myunsw_ prefix
        all_cookies = config.load_cookies()
        for key, value in cookies.items():
            all_cookies[f"myunsw_{key}"] = value
        config.save_cookies(all_cookies)
        print_success("myUNSW session cookies captured and saved!")

        # Save browser storage state for future use
        if storage_state:
            try:
                from unsw.config import CONFIG_DIR

                state_path = CONFIG_DIR / "myunsw_storage.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                with open(state_path, "w") as f:
                    json.dump(storage_state, f, indent=2, default=str)
                print_success("✓ myUNSW browser state saved for future sessions")
            except Exception as e:
                print_info(f"  (Could not write storage state: {e})")
    finally:
        # Close the browser — it's safe to close now
        try:
            await_or_run(context.close)
        except Exception:
            pass
        try:
            await_or_run(browser.close)
        except Exception:
            pass

    return True


def await_or_run(coro_func):
    """Helper: run an async cleanup function whether or not we're in an event loop."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context — schedule the close
            loop.create_task(coro_func())
        else:
            loop.run_until_complete(coro_func())
    except RuntimeError:
        asyncio.run(coro_func())


async def _browser_login_flow_with_state():
    """Like _browser_login_flow but also saves the storage_state.

    Returns (cookies, storage_state_dict, browser_ref). The caller is
    responsible for closing the browser.
    """
    from playwright.async_api import async_playwright

    print_info("Opening browser for myUNSW login...")
    print_info("")
    print_info("  A browser window will open. Follow these steps:")
    print_info("  1. Wait for the myUNSW page to load")
    print_info("  2. Log in with your UNSW zID and password (Azure AD SSO)")
    print_info("  3. If prompted, complete MFA")
    print_info("  4. After logging in, you should see the myUNSW Student Portal")
    print_info("")

    async with async_playwright() as p:
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
            # Use the clientredirect endpoint to start the SSO chain
            await page.goto(
                f"{MYUNSW_BASE}/portal/clientredirect?client_name=azuread&service=https%3A%2F%2Fmy.unsw.edu.au%2Fportal%2F",
                wait_until="commit",
                timeout=30000,
            )
        except Exception as e:
            print_info(f"  (Navigation note: {e})")

        print_info("  Browser is open. Waiting for you to log in...\n")

        await asyncio.sleep(2)

        start_time = time.time()
        captured_cookies = None

        # Wait for the user to fully complete login AND land on the
        # myUNSW dashboard (not just any SSO redirect). We do this by
        # checking the browser's current URL: once we're past the SSO
        # login pages and on a real myUNSW page, the user is logged in.
        while time.time() - start_time < TIMEOUT:
            try:
                current_url = (page.url or "").lower()

                # Skip if we're still on a login page
                on_login_page = any(
                    fragment in current_url
                    for fragment in (
                        "sso.unsw.edu.au/cas/login",
                        "login.microsoftonline.com",
                        "login.live.com",
                    )
                )
                if on_login_page:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # Skip if we're on the public myUNSW search page
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
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # Now we should be on a logged-in myUNSW page. Capture
                # the cookies and verify.
                cookies = await context.cookies()
                cookies_dict = {}
                for c in cookies:
                    if not c.get("value"):
                        continue
                    cookies_dict[c["name"]] = c["value"]

                # Make sure we have *some* real session cookie, not just
                # the public page's AWSALB/etc.
                has_real_session = any(
                    name in cookies_dict
                    for name in (
                        "JSESSIONID",
                        "PS_TOKEN",
                        "DISSESSIONAuthnDelegation",
                        "ESTSAUTHPERSISTENT",
                    )
                )
                if not has_real_session:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue

                # Final confirmation: the verifier returns True
                if await _verify_session_async(cookies_dict):
                    # Prime the /active/ session so the BSDS endpoints
                    # get a JSESSIONID cookie scoped to path=/active.
                    try:
                        print_info(
                            "  Establishing /active session for BSDS endpoints..."
                        )
                        await page.goto(
                            f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml",
                            wait_until="domcontentloaded",
                            timeout=15000,
                        )
                        await asyncio.sleep(1.5)
                        all_cookies = await context.cookies()
                        for c in all_cookies:
                            if c.get("value"):
                                cookies_dict[c["name"]] = c["value"]
                    except Exception as e:
                        print_info(f"  (Could not prime /active session: {e})")

                    captured_cookies = cookies_dict
                    print_info("\n  ✅ myUNSW session verified! Login successful!")
                    break
            except Exception:
                pass

        await asyncio.sleep(POLL_INTERVAL)

        if not captured_cookies:
            print_info(f"\n  Timeout ({TIMEOUT // 60} min) reached.")
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            return None

        # Capture storage_state while the context is still alive
        try:
            storage_state = await context.storage_state()
        except Exception as e:
            print_warning(f"Could not capture storage state: {e}")
            storage_state = None

        return captured_cookies, storage_state, browser, context


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
            # Use the clientredirect endpoint to start the SSO chain
            await page.goto(
                f"{MYUNSW_BASE}/portal/clientredirect?client_name=azuread&service=https%3A%2F%2Fmy.unsw.edu.au%2Fportal%2F",
                wait_until="commit",
                timeout=30000,
            )
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
                        # Prime the /active/ session so the BSDS endpoints
                        # get a JSESSIONID cookie scoped to path=/active.
                        try:
                            print_info(
                                "  Establishing /active session for BSDS endpoints..."
                            )
                            await page.goto(
                                f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml",
                                wait_until="domcontentloaded",
                                timeout=15000,
                            )
                            await asyncio.sleep(1.5)
                            all_cookies = await context.cookies()
                            for c in all_cookies:
                                if c.get("value") and (
                                    MYUNSW_BASE in c.get("domain", "")
                                    or c["name"]
                                    in ("PS_TOKEN", "PS_TOKENEXPIRE", "myunsw_session")
                                ):
                                    myunsw_cookies[c["name"]] = c["value"]
                        except Exception as e:
                            print_info(f"  (Could not prime /active session: {e})")

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

    IMPORTANT: We do NOT use 'buid' as a session indicator. That cookie
    is set by UNSW as a browser-unique ID on first visit, well before the
    user logs in. Using it causes premature 'verified' detection.
    """
    # Strong indicators that the user is logged in:
    # - ESTSAUTHPERSISTENT on Azure AD (set AFTER successful login)
    # - SignInStateCookie on Azure AD (set AFTER successful login)
    # - DISSESSIONAuthnDelegation on myUNSW (set AFTER successful login)
    # - JSESSIONID on myUNSW (session id, set after login)
    # - PS_TOKEN on myUNSW (legacy PeopleSoft session)

    # buid is intentionally excluded — it's set too early to be a
    # reliable auth indicator.

    # Direct check on the cookies we got (assumes they're already filtered
    # by domain in the caller)
    strong_indicators = {
        "ESTSAUTHPERSISTENT",
        "SignInStateCookie",
        "DISSESSIONAuthnDelegation",
        "PS_TOKEN",
    }
    if any(name in strong_indicators for name in cookies):
        return True

    # If we have a JSESSIONID, try the actual myUNSW endpoint to see if
    # it grants us access. JSESSIONID alone is not proof — it can be a
    # pre-session cookie set before login.
    if "JSESSIONID" in cookies:
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
        # Try the /active/ BSDS endpoint first — this is the most reliable
        # indicator that the session has a /active-scoped JSESSIONID and the
        # TGC SSO cookie are both alive.
        try:
            resp = client.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml")
            if resp.status_code == 200:
                # A real BSDS page will contain a bsdsSequence hidden field
                if 'bsdsSequence" value="' in resp.text:
                    return True
                # Otherwise it's the CAS login page
                return False
            # If we get a redirect, see where it goes
            location = resp.headers.get("location", "")
            if resp.status_code in (302, 303, 307, 308):
                if (
                    "login" not in location.lower()
                    and "sso.unsw.edu.au" not in location
                    and "login.microsoftonline" not in location
                ):
                    return True
                return False
        except Exception:
            pass

        # Fallback: try the /portal/ page
        try:
            resp = client.get(f"{MYUNSW_BASE}/portal/")
            if resp.status_code == 200:
                # 200 on /portal/ is the public search page (not authed)
                if (
                    "Sign On" not in resp.text
                    and "Apply Online" not in resp.text
                    and "Single Sign On" not in resp.text
                ):
                    return True
                return False
            # If we get a redirect that's NOT to a login page, we're authed
            location = resp.headers.get("location", "")
            if resp.status_code in (302, 303, 307, 308):
                if (
                    "login" not in location.lower()
                    and "sso.unsw.edu.au" not in location
                    and "login.microsoftonline" not in location
                ):
                    return True
                return False
        except Exception:
            pass
        return False

    return False


def verify_session(config: Config) -> bool:
    """Verify stored myUNSW session cookies are still valid.

    This is a fast check that looks at strong indicators (Azure AD SSO
    cookies, DISSESSIONAuthnDelegation, PS_TOKEN). It does NOT make an
    HTTP request. Use this for status display.

    For a strict check that actually hits the BSDS endpoint, use
    verify_bsds_session().
    """
    saved = config.load_cookies()
    myunsw_cookies = {
        k.removeprefix("myunsw_"): v
        for k, v in saved.items()
        if k.startswith("myunsw_")
    }
    if not myunsw_cookies:
        return False
    return _check_session_cookies(myunsw_cookies)


def verify_bsds_session(config: Config) -> bool:
    """Strict verification: hits the BSDS /active/ endpoint to confirm
    the session is alive and the JSESSIONID is properly scoped.

    This is slower (one HTTP request) but more reliable than
    verify_session(). Use this before actually trying to fetch data.
    """
    saved = config.load_cookies()
    myunsw_cookies = {
        k.removeprefix("myunsw_"): v
        for k, v in saved.items()
        if k.startswith("myunsw_")
    }
    if not myunsw_cookies:
        return False
    if not _check_session_cookies(myunsw_cookies):
        return False
    # Also verify the BSDS endpoint responds with a real BSDS page.
    client = httpx.Client(
        follow_redirects=True,
        timeout=15.0,
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
    try:
        resp = client.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml")
        if resp.status_code != 200:
            return False
        # Real BSDS page contains a bsdsSequence hidden input
        return 'bsdsSequence" value="' in resp.text
    except Exception:
        return False
    finally:
        client.close()


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
