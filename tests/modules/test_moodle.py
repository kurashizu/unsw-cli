"""Tests for unsw/modules/moodle.py — course, assignment, grade scraping."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.auth.moodle import MOODLE_BASE
from unsw.modules.moodle import MoodleModule


class TestMoodleCourses:
    """Tests for get_courses()."""

    @respx.mock
    def test_parses_course_cards(
        self, config_with_moodle_cookie, moodle_dashboard_html
    ):
        """Should extract course IDs from dashboard course cards."""
        respx.get(f"{MOODLE_BASE}/my/").mock(
            return_value=httpx.Response(200, text=moodle_dashboard_html)
        )

        module = MoodleModule(config_with_moodle_cookie)
        courses = module.get_courses()

        assert len(courses) == 2
        codes = {c["id"] for c in courses}
        assert "12345" in codes
        assert "12346" in codes

    @respx.mock
    def test_no_client_returns_empty(self, isolated_config):
        """No authenticated client → empty list."""
        module = MoodleModule(isolated_config)
        assert module.get_courses() == []


class TestMoodleAssignments:
    """Tests for get_assignments()."""

    @respx.mock
    def test_no_assignments_found(self, config_with_moodle_cookie):
        """Empty dashboard returns empty assignments list."""
        empty_html = "<html><body>No assignments</body></html>"
        respx.get(f"{MOODLE_BASE}/my/").mock(
            return_value=httpx.Response(200, text=empty_html)
        )
        respx.get(url__regex=r"calendar/view\.php").mock(
            return_value=httpx.Response(200, text=empty_html)
        )

        module = MoodleModule(config_with_moodle_cookie)
        assert module.get_assignments() == []


class TestMoodleGrades:
    """Tests for get_grades()."""

    @respx.mock
    def test_grades_requires_client(self, isolated_config):
        """Without a client, returns empty list."""
        module = MoodleModule(isolated_config)
        assert module.get_grades() == []


class TestMoodleEvents:
    """Tests for get_upcoming_events()."""

    @respx.mock
    def test_no_events_returns_empty(self, config_with_moodle_cookie):
        """Empty calendar returns empty events."""
        empty = "<html><body></body></html>"
        respx.get(url__regex=r"calendar/view\.php").mock(
            return_value=httpx.Response(200, text=empty)
        )
        module = MoodleModule(config_with_moodle_cookie)
        assert module.get_upcoming_events() == []
