"""Moodle authentication - cookie-based only.

Moodle uses Azure AD SSO (SAML/OIDC) which is complex to automate.
UNSW Moodle has NOT enabled the REST API web service, so API tokens
are not available. The only way to authenticate is via the MoodleSession
cookie, which can be:

1. Auto-captured via browser: unsw login --browser
2. Manually exported from browser: unsw login --set-cookie MoodleSession=...
"""

from __future__ import annotations

from typing import Optional

import httpx

from unsw.config import Config
from unsw.utils.output import print_error, print_success, print_warning

MOODLE_BASE = "https://moodle.telt.unsw.edu.au"


def verify_cookie(cookie_value: str) -> bool:
    """Verify a MoodleSession cookie is still valid."""
    client = httpx.Client(
        follow_redirects=False,
        timeout=15.0,
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
        resp = client.get(f"{MOODLE_BASE}/my/")
        return not (
            resp.status_code in (302, 303, 307, 308) or "login" in str(resp.url)
        )
    except Exception:
        return False


def login_with_cookie(config: Config) -> httpx.Client | None:
    """Create an authenticated Moodle client using the MoodleSession cookie.

    The user must export this cookie from their browser after logging into
    https://moodle.telt.unsw.edu.au via Azure AD SSO.
    """
    # First, check config for cookie
    cookie = None

    # Check config field
    if config.auth.moodle_session_cookie:
        cookie = config.auth.moodle_session_cookie

    # Check saved cookies file
    if not cookie:
        saved = config.load_cookies()
        cookie = saved.get("MoodleSession")

    if not cookie:
        print_error(
            "MoodleSession cookie not found.\n"
            "  1. Run: unsw login --browser\n"
            "  Or manually export the cookie from your browser:\n"
            "  unsw login --set-cookie MoodleSession=<value>"
        )
        return None

    client = httpx.Client(
        follow_redirects=True,
        timeout=30.0,
        cookies={"MoodleSession": cookie},
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

    # Verify the cookie works
    try:
        resp = client.get(f"{MOODLE_BASE}/my/", follow_redirects=False)
        # If we get redirected to login page, cookie is invalid
        if resp.status_code in (302, 303, 307, 308) or "login" in str(resp.url):
            print_warning("MoodleSession cookie appears to be expired or invalid.")
            print_warning("Please log in again: unsw login --browser")
            return None
        print_success("Moodle session authenticated!")
        return client
    except Exception as e:
        print_error(f"Moodle connection error: {e}")
        return None
