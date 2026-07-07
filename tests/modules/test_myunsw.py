"""Tests for unsw/modules/myunsw.py — enrolled courses, search, timetable."""

from __future__ import annotations

import re

from unsw.modules.myunsw import MyUNSWModule


class TestMyUNSWCourses:
    """Tests for get_enrolled_courses()."""

    def test_parses_enrolled_courses_logic(self):
        """The course-code extraction logic should find codes in rendered HTML."""
        html = """
        <html><body>
            <div>You are enrolled in COMP6733 - IoT Engineering - 2026 T2</div>
            <div>Also enrolled: COMP9319 - Web Data Compression - 2026 T2</div>
            <div>COMP9444 - Neural Networks - 2026 T2</div>
        </body></html>
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        full_text = soup.get_text(" ", strip=True)
        codes = re.findall(r"[A-Z]{4}\d{4}", full_text)
        assert "COMP6733" in codes
        assert "COMP9319" in codes
        assert "COMP9444" in codes

    def test_no_session_returns_empty(self, isolated_config):
        """No myUNSW cookies → empty list (client is None)."""
        module = MyUNSWModule(isolated_config)
        assert module.get_enrolled_courses() == []


class TestMyUNSWTimetable:
    """Tests for get_timetable()."""

    def test_timetable_extraction_logic(self):
        """The timetable extraction should find day/time/location near codes."""
        from bs4 import BeautifulSoup

        html = """
        <html><body>
            <div>COMP6733 Lecture Mon 13:00-15:00 UNSW Bus 201</div>
            <div>COMP9444 Tutorial Wed 10:00-12:00 UNSW Bus 115</div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        full_text = soup.get_text(" ", strip=True)

        # Should find day names in the text
        days_found = re.findall(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*", full_text)
        assert "Mon" in days_found
        assert "Wed" in days_found

        # Should find time patterns in the text
        time_match = re.search(r"\d{1,2}:\d{2}.{0,5}\d{1,2}:\d{2}", full_text)
        assert time_match is not None

    def test_no_session_returns_empty(self, isolated_config):
        """No myUNSW cookies → empty list."""
        module = MyUNSWModule(isolated_config)
        assert module.get_timetable() == []


class TestMyUNSWClassSearch:
    """Tests for search_classes()."""

    def test_search_classes_no_session(self, isolated_config):
        """Without session, returns empty list."""
        module = MyUNSWModule(isolated_config)
        assert module.search_classes("COMP2521") == []
