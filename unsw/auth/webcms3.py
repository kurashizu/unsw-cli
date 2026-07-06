"""WebCMS3 authentication - direct zID + zPass login with CSRF token."""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from unsw.config import Config
from unsw.utils.output import print_error, print_success

WEBCMS3_BASE = "https://webcms3.cse.unsw.edu.au"
LOGIN_URL = f"{WEBCMS3_BASE}/login"


def get_csrf_token(client: httpx.Client) -> str:
    """Fetch the login page and extract CSRF token."""
    resp = client.get(LOGIN_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Try meta tag first
    meta = soup.find("meta", attrs={"name": "csrf-token"})
    if meta and meta.get("content"):
        return meta["content"]

    # Fallback: hidden input
    inp = soup.find("input", attrs={"name": "csrf_token"})
    if inp and inp.get("value"):
        return inp["value"]

    # Another fallback: form input with name csrf_token
    inp = soup.find("input", {"name": "csrf_token"})
    if inp and inp.get("value"):
        return inp["value"]

    return ""


def verify_credentials(zid: str, zpass: str) -> bool:
    """Verify WebCMS3 credentials without saving anything."""
    import httpx
    from bs4 import BeautifulSoup

    client = httpx.Client(follow_redirects=True, timeout=15.0)
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
        # Get CSRF token
        resp = client.get(LOGIN_URL)
        soup = BeautifulSoup(resp.text, "html.parser")
        csrf_token = ""
        meta = soup.find("meta", attrs={"name": "csrf-token"})
        if meta and meta.get("content"):
            csrf_token = meta["content"]
        if not csrf_token:
            inp = soup.find("input", attrs={"name": "csrf_token"})
            if inp and inp.get("value"):
                csrf_token = inp["value"]

        if not csrf_token:
            return False

        # Attempt login (same URL, POST method)
        resp = client.post(
            LOGIN_URL,
            data={
                "zid": zid,
                "password": zpass,
                "csrf_token": csrf_token,
            },
        )

        # Check for session cookie (most reliable indicator)
        cookies = dict(client.cookies)
        if cookies.get("webcms3_session"):
            return True

        # Fallback: check URL - successful login redirects away from /login
        return not ("login" in str(resp.url).lower() and resp.url.path != "/")
    except Exception:
        return False


def login(config: Config) -> httpx.Client | None:
    """Log into WebCMS3 using zID + zPass.

    Returns an authenticated HTTPX client, or None on failure.
    Also saves session cookies to config.
    """
    zid = config.auth.zid
    zpass = config.auth.zpass

    if not zid or not zpass:
        print_error("zID or zPass not configured. Run 'unsw login' first.")
        return None

    client = httpx.Client(follow_redirects=True, timeout=30.0)
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
        # Step 1: Get CSRF token
        csrf_token = get_csrf_token(client)
        if not csrf_token:
            print_error("Could not extract CSRF token from login page.")
            return None

        # Step 2: Post login credentials (same URL, POST method)
        login_data = {
            "zid": zid,
            "password": zpass,
            "csrf_token": csrf_token,
        }
        resp = client.post(LOGIN_URL, data=login_data)
        resp.raise_for_status()

        # Step 3: Check if login succeeded
        # After successful login, we should be redirected to dashboard
        if "login" in str(resp.url).lower() and resp.url.path != "/":
            # Check for error messages in response
            soup = BeautifulSoup(resp.text, "html.parser")
            error_elem = soup.select_one(".alert-danger, .error, .alert-error")
            if error_elem:
                print_error(f"Login failed: {error_elem.get_text(strip=True)}")
                return None
            print_error("Login failed - please check your zID and zPass.")
            return None

        # Save cookies
        cookies = dict(client.cookies)
        config.save_cookies({"webcms3": cookies.get("webcms3_session", "")})
        print_success("WebCMS3 login successful!")
        return client

    except httpx.HTTPStatusError as e:
        print_error(f"WebCMS3 login HTTP error: {e.response.status_code}")
        return None
    except httpx.RequestError as e:
        print_error(f"WebCMS3 login network error: {e}")
        return None
    except Exception as e:
        print_error(f"WebCMS3 login error: {e}")
        return None
