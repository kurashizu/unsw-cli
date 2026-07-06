"""Tests for unsw/modules/timetable.py — HTML table parsing."""

from __future__ import annotations

import httpx
import pytest
import respx

from unsw.modules.timetable import TimetableModule


class TestTimetableParsing:
    """Tests for get_course_classes()."""

    @respx.mock
    def test_parses_class_rows(self, timetable_html):
        """Should extract class number, section, activity, period."""
        respx.get(url__regex=r"timetable\.unsw\.edu\.au").mock(
            return_value=httpx.Response(200, text=timetable_html)
        )

        module = TimetableModule()
        classes = module.get_course_classes("COMP2521", 2026)

        assert len(classes) == 2
        assert classes[0]["class"] == "1234"
        assert classes[0]["section"] == "T13A"
        assert classes[0]["activity"] == "Lecture"
        assert classes[1]["activity"] == "Tutorial"

    @respx.mock
    def test_handles_empty_page(self):
        """Empty page should return empty list."""
        respx.get(url__regex=r"timetable\.unsw\.edu\.au").mock(
            return_value=httpx.Response(200, text="<html><body>No data</body></html>")
        )
        module = TimetableModule()
        assert module.get_course_classes("FAKE9999", 2026) == []

    @respx.mock
    def test_handles_404(self):
        """404 should return empty list."""
        respx.get(url__regex=r"timetable\.unsw\.edu\.au").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        module = TimetableModule()
        assert module.get_course_classes("FAKE9999", 2026) == []


class TestTimetableAreas:
    """Tests for search_by_year() — subject area listing."""

    @respx.mock
    def test_lists_subject_areas(self):
        """Should return subject areas with codes."""
        areas_html = """
        <html><body>
            <a href="COMPKENS.html">COMP</a>
            <a href="MATHKENS.html">MATH</a>
            <a href="SENGKENS.html">SENG</a>
        </body></html>
        """
        respx.get(url__regex=r"timetable\.unsw\.edu\.au").mock(
            return_value=httpx.Response(200, text=areas_html)
        )
        module = TimetableModule()
        areas = module.search_by_year(2026)
        assert len(areas) >= 3
