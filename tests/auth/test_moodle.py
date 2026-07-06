"""Tests for unsw/auth/moodle.py — cookie verification and login_with_cookie."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.auth.moodle import MOODLE_BASE, login_with_cookie, verify_cookie

MOODLE_DASHBOARD_AUTHED = """
<!DOCTYPE html>
<html>
<body>
    <h1>Moodle Dashboard</h1>
    <p>Welcome back</p>
</body>
</html>
"""

MOODLE_LOGIN_REDIRECT = """
<!DOCTYPE html>
<html>
<body>Redirecting to login...</body>
</html>
"""


class TestVerifyCookie:
    """Tests for verify_cookie."""

    @respx.mock
    def test_valid_cookie(self):
        """Valid cookie returns True."""
        respx.get(f"{MOODLE_BASE}/my/").mock(
            return_value=httpx.Response(200, text=MOODLE_DASHBOARD_AUTHED)
        )
        assert verify_cookie("valid_cookie_value") is True

    @respx.mock
    def test_expired_cookie_returns_false(self):
        """Expired cookie redirects to login → returns False."""
        respx.get(f"{MOODLE_BASE}/my/").mock(
            return_value=httpx.Response(
                302,
                text=MOODLE_LOGIN_REDIRECT,
                headers={"location": f"{MOODLE_BASE}/login/"},
            )
        )
        assert verify_cookie("expired_cookie") is False

    @respx.mock
    def test_network_error_returns_false(self):
        """Network errors should return False gracefully."""
        respx.get(f"{MOODLE_BASE}/my/").mock(
            side_effect=httpx.ConnectError("Connection failed")
        )
        assert verify_cookie("any_cookie") is False


class TestLoginWithCookie:
    """Tests for login_with_cookie."""

    def test_no_cookie_returns_none(self, isolated_config):
        """Returns None if no cookie is stored."""
        client = login_with_cookie(isolated_config)
        assert client is None

    @respx.mock
    def test_valid_cookie_authenticates(self, config_with_moodle_cookie):
        """Valid cookie from cookies.json → returns authenticated client."""
        # Override the fake cookie with a "valid" one for the mocked response
        config_with_moodle_cookie.save_cookies(
            {"MoodleSession": "real_cookie_for_mock"}
        )
        respx.get(f"{MOODLE_BASE}/my/").mock(
            return_value=httpx.Response(200, text=MOODLE_DASHBOARD_AUTHED)
        )

        client = login_with_cookie(config_with_moodle_cookie)
        assert client is not None
        # Cookie should be set on the client
        assert client.cookies.get("MoodleSession") == "real_cookie_for_mock"

    @respx.mock
    def test_expired_cookie_returns_none(self, config_with_moodle_cookie):
        """Expired cookie → returns None."""
        respx.get(f"{MOODLE_BASE}/my/").mock(
            return_value=httpx.Response(
                302,
                text="",
                headers={"location": f"{MOODLE_BASE}/login/"},
            )
        )
        client = login_with_cookie(config_with_moodle_cookie)
        assert client is None

    def test_config_field_cookie_used_if_no_file_cookie(self, isolated_config):
        """If no cookie in file, fall back to config.auth.moodle_session_cookie."""
        isolated_config.auth.moodle_session_cookie = "from_config_field"

        # No HTTP mock needed — we exit before verifying due to invalid cookie
        # We need to check that the function *tried* to verify the right cookie
        with respx.mock:
            import httpx as _httpx

            respx.get(f"{MOODLE_BASE}/my/").mock(
                return_value=_httpx.Response(200, text=MOODLE_DASHBOARD_AUTHED)
            )
            client = login_with_cookie(isolated_config)
            assert client is not None
            assert client.cookies.get("MoodleSession") == "from_config_field"


class TestCookieMergeBugRegression:
    """Regression tests for the save_cookies merge bug.

    Previously, save_cookies() would overwrite all cookies, deleting
    MoodleSession when WebCMS3 login was called. This must not regress.
    """

    def test_moodle_cookie_preserved_after_webcms3_save(self, isolated_config):
        """MoodleSession must survive a WebCMS3 cookie save."""
        # 1. Save Moodle cookie (simulating browser capture)
        isolated_config.save_cookies({"MoodleSession": "moodle_xyz"})
        # 2. Save WebCMS3 cookie (simulating WebCMS3 login)
        isolated_config.save_cookies({"webcms3_session": "webcms3_abc"})

        cookies = isolated_config.load_cookies()
        assert cookies.get("MoodleSession") == "moodle_xyz", (
            "MoodleSession was lost when saving WebCMS3 cookie — merge bug regressed!"
        )
        assert cookies.get("webcms3_session") == "webcms3_abc"

    def test_multiple_platforms_all_preserved(self, isolated_config):
        """All platforms' cookies should coexist in cookies.json."""
        isolated_config.save_cookies({"MoodleSession": "m1"})
        isolated_config.save_cookies({"webcms3_session": "w1"})
        isolated_config.save_cookies({"myunsw_PS_TOKEN": "p1"})

        cookies = isolated_config.load_cookies()
        assert len(cookies) == 3
        assert cookies["MoodleSession"] == "m1"
        assert cookies["webcms3_session"] == "w1"
        assert cookies["myunsw_PS_TOKEN"] == "p1"
