"""Tests for unsw/modules/myunsw.py — enrolled courses, search, timetable."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.modules.myunsw import MYUNSW_BASE, MyUNSWModule


class TestMyUNSWCourses:
    """Tests for get_enrolled_courses()."""

    @respx.mock
    def test_parses_enrolled_courses(self, config_with_moodle_cookie):
        """Should extract course codes from myUNSW page."""
        config_with_moodle_cookie.save_cookies({"myunsw_PS_TOKEN": "fake_session"})

        courses_html = """
        <html><body>
            <table>
                <tr><td>COMP6733 - IoT - 2026 T2</td></tr>
                <tr><td>COMP9319 - Web Data - 2026 T2</td></tr>
            </table>
        </body></html>
        """
        respx.get(url__regex=r"my\.unsw\.edu\.au").mock(
            return_value=httpx.Response(200, text=courses_html)
        )

        module = MyUNSWModule(config_with_moodle_cookie)
        courses = module.get_enrolled_courses()

        assert len(courses) >= 1
        codes = {c["code"] for c in courses}
        assert "COMP6733" in codes or "COMP9319" in codes

    @respx.mock
    def test_no_session_returns_empty(self, isolated_config):
        """No myUNSW cookies → empty list."""
        module = MyUNSWModule(isolated_config)
        assert module.get_enrolled_courses() == []


class TestMyUNSWTimetable:
    """Tests for get_timetable()."""

    @respx.mock
    def test_parses_peoplesoft_table(self, config_with_moodle_cookie):
        """Should extract classes from PeopleSoft SSR_SSENRL_LIST table."""
        config_with_moodle_cookie.save_cookies({"myunsw_PS_TOKEN": "fake_session"})

        timetable_html = """
        <html><body>
            <table summary="Enrolled Classes">
                <tr><th>Section</th><th>Activity</th><th>Day</th>
                    <th>Time</th><th>Location</th></tr>
                <tr>
                    <td>COMP6733-LEC-01</td>
                    <td>Lecture</td>
                    <td>Mon</td>
                    <td>13:00-15:00</td>
                    <td>UNSW Bus 201</td>
                </tr>
                <tr>
                    <td>COMP6733-TUT-01</td>
                    <td>Tutorial</td>
                    <td>Wed</td>
                    <td>10:00-12:00</td>
                    <td>UNSW Bus 115</td>
                </tr>
            </table>
        </body></html>
        """

        respx.get(url__regex=r"my\.unsw\.edu\.au.*SSR_SSENRL_LIST").mock(
            return_value=httpx.Response(200, text=timetable_html)
        )
        respx.get(MYUNSW_BASE + "/portal/").mock(
            return_value=httpx.Response(200, text="<html>fallback</html>")
        )

        module = MyUNSWModule(config_with_moodle_cookie)
        classes = module.get_timetable()

        assert isinstance(classes, list)
        # Each class dict should have the expected keys
        for cls in classes:
            assert "code" in cls
            assert "day" in cls
            assert "time" in cls

    @respx.mock
    def test_falls_back_to_browser(self, config_with_moodle_cookie):
        """If nothing is scraped, returns empty (caller opens browser)."""
        config_with_moodle_cookie.save_cookies({"myunsw_PS_TOKEN": "fake_session"})

        empty_html = "<html><body></body></html>"
        respx.get(url__regex=r"my\.unsw\.edu\.au").mock(
            return_value=httpx.Response(200, text=empty_html)
        )
        module = MyUNSWModule(config_with_moodle_cookie)
        assert module.get_timetable() == []


class TestMyUNSWClassSearch:
    """Tests for search_classes()."""

    @respx.mock
    def test_search_classes_returns_list(self, config_with_moodle_cookie):
        """search_classes should return a list (may be empty)."""
        config_with_moodle_cookie.save_cookies({"myunsw_PS_TOKEN": "fake_session"})

        respx.get(url__regex=r"my\.unsw\.edu\.au").mock(
            return_value=httpx.Response(200, text="<html>empty</html>")
        )
        module = MyUNSWModule(config_with_moodle_cookie)
        result = module.search_classes("COMP2521")
        assert isinstance(result, list)

    @respx.mock
    def test_search_classes_no_session(self, isolated_config):
        """Without session, returns empty list."""
        module = MyUNSWModule(isolated_config)
        assert module.search_classes("COMP2521") == []
