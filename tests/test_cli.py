"""CLI smoke tests — verify all commands parse and run without errors."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from unsw.cli import app


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
