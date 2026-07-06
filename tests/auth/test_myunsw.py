"""Tests for unsw/auth/myunsw.py — session verification and login_with_cookie."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.auth.myunsw import MYUNSW_BASE, login_with_cookie, verify_session


class TestVerifySession:
    """Tests for verify_session."""

    def test_no_cookies_returns_false(self, isolated_config):
        """Returns False if no myUNSW cookies are stored."""
        assert verify_session(isolated_config) is False

    @respx.mock
    def test_valid_session(self, config_with_moodle_cookie):
        """Valid myUNSW session cookies should verify successfully."""
        # Add a myUNSW cookie (prefixed)
        config_with_moodle_cookie.save_cookies(
            {"myunsw_PS_TOKEN": "fake_session_token"}
        )
        respx.get(MYUNSW_BASE + "/").mock(
            return_value=httpx.Response(200, text="<html>myUNSW portal</html>")
        )

        assert verify_session(config_with_moodle_cookie) is True

    @respx.mock
    def test_expired_session(self, config_with_moodle_cookie):
        """Session that redirects to login → returns False."""
        config_with_moodle_cookie.save_cookies({"myunsw_PS_TOKEN": "expired_token"})
        respx.get(MYUNSW_BASE + "/").mock(
            return_value=httpx.Response(
                302,
                text="",
                headers={"location": MYUNSW_BASE + "/login"},
            )
        )
        assert verify_session(config_with_moodle_cookie) is False

    @respx.mock
    def test_network_error(self, config_with_moodle_cookie):
        """Network errors → returns False gracefully."""
        config_with_moodle_cookie.save_cookies({"myunsw_PS_TOKEN": "any_token"})
        respx.get(MYUNSW_BASE + "/").mock(side_effect=httpx.ConnectError("fail"))
        assert verify_session(config_with_moodle_cookie) is False


class TestLoginWithCookie:
    """Tests for login_with_cookie."""

    def test_no_cookies_returns_none(self, isolated_config):
        """No myUNSW cookies stored → returns None."""
        client = login_with_cookie(isolated_config)
        assert client is None

    @respx.mock
    def test_valid_session_authenticates(self, isolated_config):
        """Valid stored cookies → returns authenticated client."""
        isolated_config.save_cookies({"myunsw_PS_TOKEN": "session_abc"})
        isolated_config.save_cookies({"myunsw_PS_TOKENEXPIRE": "1234567890"})

        respx.get(MYUNSW_BASE + "/").mock(
            return_value=httpx.Response(200, text="<html>portal</html>")
        )

        client = login_with_cookie(isolated_config)
        assert client is not None
        # Cookies should be stripped of the myunsw_ prefix
        assert client.cookies.get("PS_TOKEN") == "session_abc"

    @respx.mock
    def test_expired_session_returns_none(self, isolated_config):
        """Expired session → returns None."""
        isolated_config.save_cookies({"myunsw_PS_TOKEN": "expired"})

        respx.get(MYUNSW_BASE + "/").mock(
            return_value=httpx.Response(
                302,
                text="",
                headers={"location": MYUNSW_BASE + "/login"},
            )
        )
        client = login_with_cookie(isolated_config)
        assert client is None
