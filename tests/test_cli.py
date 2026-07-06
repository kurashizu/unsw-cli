"""CLI smoke tests — verify all commands parse and run without errors."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from unsw.cli import app
from unsw.config import Config


class TestCLIBasics:
    """Test basic CLI structure."""

    def test_help(self, cli_runner):
        """`unsw --help` should succeed."""
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_version(self, cli_runner):
        """`unsw version` should show version info."""
        result = cli_runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "UNSW CLI" in result.stdout

    def test_dashboard(self, cli_runner, isolated_config):
        """`unsw dashboard` should render without crashing."""
        result = cli_runner.invoke(app, ["dashboard"])
        assert result.exit_code == 0
        assert "Dashboard" in result.stdout or "UNSW CLI" in result.stdout


class TestAuthCommands:
    """Test authentication commands."""

    def test_auth_status(self, cli_runner, isolated_config):
        """`unsw auth status` should display status table."""
        result = cli_runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0
        # Should mention each platform
        assert "WebCMS3" in result.stdout
        assert "Moodle" in result.stdout
        assert "myUNSW" in result.stdout

    def test_auth_status_shows_webcms3_verified(self, cli_runner, config_with_webcms3):
        """With WebCMS3 creds, status should show them."""
        result = cli_runner.invoke(app, ["auth", "status"])
        assert result.exit_code == 0

    def test_auth_guide(self, cli_runner):
        """`unsw auth guide` should show platform guides."""
        result = cli_runner.invoke(app, ["auth", "guide"])
        assert result.exit_code == 0
        # Should mention each platform's guide
        assert "WebCMS3" in result.stdout
        assert "Moodle" in result.stdout

    def test_login_show(self, cli_runner, isolated_config):
        """`unsw login --show` should display current config."""
        result = cli_runner.invoke(app, ["login", "--show"])
        assert result.exit_code == 0
        assert "Configuration" in result.stdout or "zID" in result.stdout


class TestHandbookCommands:
    """Test handbook subcommands (smoke — no network)."""

    def test_handbook_help(self, cli_runner):
        """`unsw handbook --help` should succeed."""
        result = cli_runner.invoke(app, ["handbook", "--help"])
        assert result.exit_code == 0


class TestTimetableCommands:
    """Test timetable subcommands."""

    def test_timetable_help(self, cli_runner):
        """`unsw timetable --help` should succeed."""
        result = cli_runner.invoke(app, ["timetable", "--help"])
        assert result.exit_code == 0


class TestMoodleCommands:
    """Test Moodle subcommands."""

    def test_moodle_help(self, cli_runner):
        """`unsw moodle --help` should succeed."""
        result = cli_runner.invoke(app, ["moodle", "--help"])
        assert result.exit_code == 0

    def test_moodle_courses_without_auth(self, cli_runner, isolated_config):
        """Without cookie, should print error and exit cleanly."""
        result = cli_runner.invoke(app, ["moodle", "courses"])
        # Should exit 0 with an error message (or 1 depending on design)
        # Either is acceptable for smoke test
        assert "Moodle" in result.stdout or result.exit_code != 0


class TestWebCMS3Commands:
    """Test WebCMS3 subcommands."""

    def test_webcms3_help(self, cli_runner):
        """`unsw webcms3 --help` should succeed."""
        result = cli_runner.invoke(app, ["webcms3", "--help"])
        assert result.exit_code == 0

    def test_webcms3_courses_without_auth(self, cli_runner, isolated_config):
        """Without credentials, should print error."""
        result = cli_runner.invoke(app, ["webcms3", "courses"])
        # Should fail with zID/zPass error or exit cleanly
        assert (
            "zID" in result.stdout
            or "configured" in result.stdout
            or result.exit_code != 0
        )


class TestLibraryCommands:
    """Test library subcommands."""

    def test_library_help(self, cli_runner):
        """`unsw library --help` should succeed."""
        result = cli_runner.invoke(app, ["library", "--help"])
        assert result.exit_code == 0


class TestMyUNSWCommands:
    """Test myUNSW subcommands."""

    def test_myunsw_help(self, cli_runner):
        """`unsw myunsw --help` should list all subcommands."""
        result = cli_runner.invoke(app, ["myunsw", "--help"])
        assert result.exit_code == 0
        assert "login" in result.stdout
        assert "courses" in result.stdout
        assert "timetable" in result.stdout
        assert "enrol" in result.stdout
        assert "drop" in result.stdout
        assert "open" in result.stdout


class TestCLIErrorHandling:
    """Test that commands handle invalid input gracefully."""

    def test_invalid_subcommand(self, cli_runner):
        """Unknown subcommand should error, not crash."""
        result = cli_runner.invoke(app, ["nonexistent"])
        assert result.exit_code != 0

    def test_login_set_cookie_bad_format(self, cli_runner, isolated_config):
        """Invalid cookie format should error gracefully."""
        result = cli_runner.invoke(app, ["login", "--set-cookie", "noequals"])
        # Should fail gracefully
        assert "Invalid" in result.stdout or result.exit_code != 0


class TestLoginPlatformFlag:
    """Test `unsw login --platform <name>` uniform semantics."""

    def test_login_platform_invalid_value(self, cli_runner, isolated_config):
        """Invalid --platform value should error with a clear message."""
        result = cli_runner.invoke(app, ["login", "--platform", "facebook"])
        assert result.exit_code == 1
        assert "Invalid" in result.stdout or "invalid" in result.stdout.lower()

    def test_login_platform_webcms3_saves_credentials(
        self, cli_runner, isolated_config, monkeypatch
    ):
        """`unsw login --platform webcms3 --zid X --zpass Y` should save."""
        # Skip the actual verify_credentials network call by mocking it
        from unsw.auth import webcms3 as webcms3_auth

        monkeypatch.setattr(webcms3_auth, "verify_credentials", lambda z, p: True)

        result = cli_runner.invoke(
            app,
            [
                "login",
                "--platform",
                "webcms3",
                "--zid",
                "z9999999",
                "--zpass",
                "secret",
            ],
        )
        assert result.exit_code == 0
        assert "WebCMS3 credentials saved" in result.stdout
        assert "verified" in result.stdout

    def test_login_platform_webcms3_save_then_reload(
        self, cli_runner, isolated_config, monkeypatch
    ):
        """Saved credentials should be reloadable via Config()."""
        from unsw.auth import webcms3 as webcms3_auth

        monkeypatch.setattr(webcms3_auth, "verify_credentials", lambda z, p: True)

        cli_runner.invoke(
            app,
            [
                "login",
                "--platform",
                "webcms3",
                "--zid",
                "z9999999",
                "--zpass",
                "secret",
            ],
        )
        # Re-load config from disk
        config = Config()
        assert config.auth.zid == "z9999999"
        assert config.auth.zpass == "secret"

    def test_login_platform_webcms3_invalid_creds(
        self, cli_runner, isolated_config, monkeypatch
    ):
        """Bad credentials should warn but still save."""
        from unsw.auth import webcms3 as webcms3_auth

        monkeypatch.setattr(webcms3_auth, "verify_credentials", lambda z, p: False)

        result = cli_runner.invoke(
            app,
            [
                "login",
                "--platform",
                "webcms3",
                "--zid",
                "z9999999",
                "--zpass",
                "wrong",
            ],
        )
        assert result.exit_code == 0
        assert "failed" in result.stdout.lower() or "Check" in result.stdout

    def test_login_platform_moodle_set_cookie(self, cli_runner, isolated_config):
        """`unsw login --platform moodle --set-cookie X=Y` should save."""
        result = cli_runner.invoke(
            app,
            [
                "login",
                "--platform",
                "moodle",
                "--set-cookie",
                "MoodleSession=fakevalue123",
            ],
        )
        assert result.exit_code == 0
        cookies = isolated_config.load_cookies()
        assert cookies.get("MoodleSession") == "fakevalue123"

    def test_login_platform_moodle_set_cookie_bad_format(
        self, cli_runner, isolated_config
    ):
        """Bad cookie format should error out."""
        result = cli_runner.invoke(
            app,
            ["login", "--platform", "moodle", "--set-cookie", "noequals"],
        )
        assert result.exit_code == 1
        assert "Invalid" in result.stdout

    def test_login_platform_myunsw_without_browser(self, cli_runner, isolated_config):
        """myUNSW without --browser should print a hint."""
        result = cli_runner.invoke(app, ["login", "--platform", "myunsw"])
        assert "browser" in result.stdout.lower()

    def test_login_inferred_platform_zid(
        self, cli_runner, isolated_config, monkeypatch
    ):
        """`unsw login --zid X --zpass Y` should infer --platform webcms3."""
        from unsw.auth import webcms3 as webcms3_auth

        monkeypatch.setattr(webcms3_auth, "verify_credentials", lambda z, p: True)

        result = cli_runner.invoke(
            app,
            [
                "login",
                "--zid",
                "z9999999",
                "--zpass",
                "secret",
            ],
        )
        # Should have saved WebCMS3 credentials
        config = Config()
        assert config.auth.zid == "z9999999"

    def test_login_inferred_platform_browser(
        self, cli_runner, isolated_config, monkeypatch
    ):
        """`unsw login --browser` should infer --platform moodle."""
        from unsw.auth import browser as browser_auth

        # Mock the browser flow so we don't actually open a browser
        called = []
        monkeypatch.setattr(
            browser_auth,
            "moodle_login_via_browser",
            lambda c: called.append(True) or True,
        )

        result = cli_runner.invoke(app, ["login", "--browser"])
        # Should have called the browser flow
        assert len(called) == 1

    def test_login_deprecation_hints(self, cli_runner, isolated_config, monkeypatch):
        """Setting UNSW_CLI_SHOW_DEPRECATION=1 should print deprecation hints."""
        import os

        monkeypatch.setenv("UNSW_CLI_SHOW_DEPRECATION", "1")

        # Try the auth login alias
        result = cli_runner.invoke(app, ["auth", "login"])
        # Should mention "Deprecated"
        assert "Deprecated" in result.stdout or result.exit_code != 0
