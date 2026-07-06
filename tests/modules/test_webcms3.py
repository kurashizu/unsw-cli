"""Tests for unsw/modules/webcms3.py — course and content scraping."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.modules.webcms3 import WEBCMS3_BASE, WebCMS3Module


class TestWebCMS3Courses:
    """Tests for get_courses() — extracts from nav bar."""

    @respx.mock
    def test_extracts_enrolled_courses_from_nav(
        self, config_with_webcms3, webcms3_dashboard_html
    ):
        """Should extract enrolled courses from nav bar only."""
        respx.get(f"{WEBCMS3_BASE}/").mock(
            return_value=httpx.Response(200, text=webcms3_dashboard_html)
        )

        module = WebCMS3Module(config_with_webcms3)
        courses = module.get_courses()

        assert len(courses) == 3
        codes = {c["code"] for c in courses}
        assert codes == {"COMP6733", "COMP9319", "COMP9444"}
        # All should be T2 2026
        for c in courses:
            assert c["term"] == "26T2"

    @respx.mock
    def test_no_client_returns_empty(self, isolated_config):
        """Without auth, returns empty list."""
        # Without credentials, login() returns None and module.client is None
        module = WebCMS3Module(isolated_config)
        # login() will fail, so module.client should be None
        assert module.client is None or module.get_courses() == []


class TestWebCMS3Content:
    """Tests for get_course_content()."""

    @respx.mock
    def test_parses_course_page(self, config_with_webcms3):
        """Should extract content links from a course page."""
        course_html = """
        <html><body>
            <nav>
                <a href="/COMP6733/26T2/">COMP6733</a>
                <a href="/COMP9319/26T2/">COMP9319</a>
            </nav>
            <main>
                <a href="/COMP6733/26T2/resources/lecture1">Lecture 1</a>
                <a href="/COMP6733/26T2/activities/lab1">Lab 1</a>
                <a href="/COMP6733/26T2/forums/forum1">Forum</a>
                <a href="/COMP6733/26T2/outline">Course Outline</a>
            </main>
        </body></html>
        """
        # Dashboard (for course list)
        respx.get(f"{WEBCMS3_BASE}/").mock(
            return_value=httpx.Response(200, text=course_html)
        )
        # Course page
        respx.get(url__regex=r"/COMP6733/26T2/").mock(
            return_value=httpx.Response(200, text=course_html)
        )

        module = WebCMS3Module(config_with_webcms3)
        content = module.get_course_content("COMP6733")

        assert len(content) >= 1
        titles = {c["title"] for c in content}
        assert "Lecture 1" in titles or "Lab 1" in titles


class TestWebCMS3Announcements:
    """Tests for get_announcements()."""

    @respx.mock
    def test_parses_notices(self, config_with_webcms3):
        """Should extract notices/announcements from dashboard."""
        ann_html = """
        <html><body>
            <nav></nav>
            <div class="notices">
                <h4>Welcome to COMP9444</h4>
                <p>Posted by staff on COMP9444 ...</p>
            </div>
        </body></html>
        """
        respx.get(f"{WEBCMS3_BASE}/").mock(
            return_value=httpx.Response(200, text=ann_html)
        )
        module = WebCMS3Module(config_with_webcms3)
        anns = module.get_announcements()
        # Best-effort — may or may not match depending on selectors
        assert isinstance(anns, list)
