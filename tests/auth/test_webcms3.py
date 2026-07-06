"""Tests for unsw/auth/webcms3.py — login, verification, CSRF handling."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.auth.webcms3 import (
    LOGIN_URL,
    WEBCMS3_BASE,
    get_csrf_token,
    login,
    verify_credentials,
)

WEBCMS3_LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta name="csrf-token" content="test_csrf_token_abc123">
</head>
<body>
    <form>
        <input type="hidden" name="csrf_token" value="fallback_csrf">
    </form>
</body>
</html>
"""

WEBCMS3_LOGIN_HTML_NO_META = """
<!DOCTYPE html>
<html>
<body>
    <form>
        <input type="hidden" name="csrf_token" value="form_only_csrf">
    </form>
</body>
</html>
"""

WEBCMS3_DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<body>
    <h1>WebCMS3 Dashboard</h1>
    <p>Welcome</p>
</body>
</html>
"""


class TestGetCSRFToken:
    """Tests for CSRF token extraction."""

    @respx.mock
    def test_csrf_from_meta_tag(self):
        """Should extract CSRF token from <meta name='csrf-token'>."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text=WEBCMS3_LOGIN_HTML)
        )
        with httpx.Client() as client:
            token = get_csrf_token(client)
        assert token == "test_csrf_token_abc123"

    @respx.mock
    def test_csrf_fallback_to_input(self):
        """Should fall back to input[name=csrf_token] when no meta."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text=WEBCMS3_LOGIN_HTML_NO_META)
        )
        with httpx.Client() as client:
            token = get_csrf_token(client)
        assert token == "form_only_csrf"

    @respx.mock
    def test_csrf_missing_returns_empty(self):
        """Should return empty string when no CSRF token found."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text="<html><body>No form</body></html>")
        )
        with httpx.Client() as client:
            token = get_csrf_token(client)
        assert token == ""


class TestVerifyCredentials:
    """Tests for verify_credentials."""

    @respx.mock
    def test_valid_credentials(self):
        """Valid zID+zPass with session cookie should return True."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text=WEBCMS3_LOGIN_HTML)
        )
        # POST returns 200 with dashboard HTML + sets session cookie
        respx.post(LOGIN_URL).mock(
            return_value=httpx.Response(
                200,
                text=WEBCMS3_DASHBOARD_HTML,
                headers={"set-cookie": "webcms3_session=fakesession123; Path=/"},
            )
        )

        assert verify_credentials("z1234567", "password") is True

    @respx.mock
    def test_invalid_credentials(self):
        """Bad credentials should return False."""
        # The mock returns the login page even on POST (failed login)
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text=WEBCMS3_LOGIN_HTML)
        )
        respx.post(LOGIN_URL).mock(
            return_value=httpx.Response(
                200,
                text="<html>Invalid credentials</html>",
                headers={"location": "/login"},
            )
        )
        assert verify_credentials("z1234567", "wrongpass") is False

    @respx.mock
    def test_no_csrf_token_returns_false(self):
        """If CSRF can't be extracted, return False."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text="<html>no csrf</html>")
        )
        assert verify_credentials("z1234567", "password") is False

    @respx.mock
    def test_network_error_returns_false(self):
        """Network errors should return False gracefully."""
        respx.get(LOGIN_URL).mock(side_effect=httpx.ConnectError("Connection failed"))
        assert verify_credentials("z1234567", "password") is False


class TestLogin:
    """Tests for the login() function."""

    @respx.mock
    def test_login_saves_session_cookie(self, isolated_config):
        """Login should save the webcms3_session cookie."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text=WEBCMS3_LOGIN_HTML)
        )
        respx.post(LOGIN_URL).mock(
            return_value=httpx.Response(
                200,
                text=WEBCMS3_DASHBOARD_HTML,
                headers={"set-cookie": "webcms3_session=session_xyz; Path=/"},
            )
        )

        isolated_config.auth.zid = "z1234567"
        isolated_config.auth.zpass = "mypass"

        client = login(isolated_config)
        assert client is not None

        cookies = isolated_config.load_cookies()
        # Cookie is stored under the key "webcms3" for namespacing
        assert "webcms3" in cookies
        assert cookies["webcms3"] == "session_xyz"

    def test_login_missing_credentials_returns_none(self, isolated_config):
        """Login without credentials should return None."""
        isolated_config.auth.zid = ""
        isolated_config.auth.zpass = ""
        client = login(isolated_config)
        assert client is None

    @respx.mock
    def test_login_failure_returns_none(self, isolated_config):
        """Login with bad credentials should return None."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text=WEBCMS3_LOGIN_HTML)
        )
        # POST returns login page (failed login)
        respx.post(LOGIN_URL).mock(
            return_value=httpx.Response(
                200,
                text="<html><body>Login failed</body></html>",
            )
        )
        isolated_config.auth.zid = "z1234567"
        isolated_config.auth.zpass = "badpass"

        client = login(isolated_config)
        assert client is None

    @respx.mock
    def test_login_csrf_failure_returns_none(self, isolated_config):
        """Login should fail gracefully if CSRF can't be extracted."""
        respx.get(LOGIN_URL).mock(
            return_value=httpx.Response(200, text="<html>no csrf</html>")
        )
        isolated_config.auth.zid = "z1234567"
        isolated_config.auth.zpass = "mypass"

        client = login(isolated_config)
        assert client is None
