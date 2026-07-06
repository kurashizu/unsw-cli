"""Tests for unsw/auth/sso.py — unified SSO login flow."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.auth.sso import MOODLE_URL, MYUNSW_URL, _verify_myunsw_session


class TestSSOVerifyHelpers:
    """Tests for the verification helpers used by the SSO flow."""

    @pytest.mark.asyncio
    @respx.mock
    async def test_verify_moodle_cookie_valid(self):
        """Valid MoodleSession should verify True."""
        from unsw.auth.sso import _verify_moodle_cookie

        respx.get(f"{MOODLE_URL}/my/").mock(
            return_value=httpx.Response(200, text="<html>Dashboard</html>")
        )
        assert await _verify_moodle_cookie("valid_value") is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_verify_moodle_cookie_redirect_to_login(self):
        """Redirect to login → invalid."""
        from unsw.auth.sso import _verify_moodle_cookie

        respx.get(f"{MOODLE_URL}/my/").mock(
            return_value=httpx.Response(
                302,
                text="",
                headers={"location": f"{MOODLE_URL}/login/"},
            )
        )
        assert await _verify_moodle_cookie("expired") is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_verify_myunsw_session_direct_200(self):
        """Direct 200 to myUNSW dashboard → valid."""
        respx.get(MYUNSW_URL + "/").mock(
            return_value=httpx.Response(200, text="<html>Student Portal</html>")
        )
        assert await _verify_myunsw_session({"PS_TOKEN": "abc"}) is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_verify_myunsw_session_redirect_to_myunsw(self):
        """Redirect to myUNSW root → valid (already authed)."""
        # First request returns a redirect to myUNSW itself
        respx.get(MYUNSW_URL + "/").mock(
            return_value=httpx.Response(
                302,
                text="",
                headers={"location": f"{MYUNSW_URL}/portal"},
            )
        )
        # Following that redirect lands on a portal page
        respx.get(f"{MYUNSW_URL}/portal").mock(
            return_value=httpx.Response(200, text="<html>Portal</html>")
        )
        assert await _verify_myunsw_session({"PS_TOKEN": "abc"}) is True

    @pytest.mark.asyncio
    @respx.mock
    async def test_verify_myunsw_session_redirect_to_login(self):
        """Redirect to login URL → invalid."""
        respx.get(MYUNSW_URL + "/").mock(
            return_value=httpx.Response(
                302,
                text="",
                headers={"location": f"{MYUNSW_URL}/login"},
            )
        )
        assert await _verify_myunsw_session({}) is False

    @pytest.mark.asyncio
    @respx.mock
    async def test_verify_myunsw_network_error(self):
        """Network errors → False (gracefully)."""
        respx.get(MYUNSW_URL + "/").mock(side_effect=httpx.ConnectError("fail"))
        assert await _verify_myunsw_session({}) is False


class TestSSOLoginAll:
    """Tests for the top-level sso_login_all function."""

    def test_missing_playwright_returns_empty(self, monkeypatch):
        """If Playwright is missing, return empty results dict."""
        from unsw.auth import sso as sso_auth
        from unsw.auth.browser import BrowserLoginError

        def fake_check():
            raise BrowserLoginError("Playwright not installed")

        monkeypatch.setattr(sso_auth, "_check_playwright", fake_check)

        from unsw.config import Config

        config = Config()
        result = sso_auth.sso_login_all(config, platforms=["moodle", "myunsw"])
        assert result == {}

    def test_invalid_platform_filtered_out(self, monkeypatch):
        """Unknown platforms are silently dropped."""
        from unsw.auth import sso as sso_auth

        monkeypatch.setattr(sso_auth, "_check_playwright", lambda: None)
        monkeypatch.setattr(sso_auth, "_ensure_chromium_installed", lambda: None)

        from unsw.config import Config

        config = Config()
        # All platforms unknown → returns empty dict with no error
        result = sso_auth.sso_login_all(config, platforms=["facebook", "twitter"])
        assert result == {}
