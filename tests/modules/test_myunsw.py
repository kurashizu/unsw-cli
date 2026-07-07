"""Tests for unsw/modules/myunsw.py — BSDS protocol, courses, timetable, grades.

The BsdsClient now drives a headless Playwright browser with the saved
storage_state. We mock Playwright's page.goto/page.content at the unit
level rather than mocking HTTP responses.
"""

from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from unsw.modules.myunsw import (
    DAY_NAMES,
    KNOWN_TERMS,
    MYUNSW_BASE,
    BsdsClient,
    MyUNSWModule,
    _extract_bsds_sequence,
    _extract_current_term,
    _find_course_codes,
    _parse_grades_html,
    _term_code_to_label,
)

# ── Sample BSDS HTML fixtures ───────────────────────────────────


YEARS_HTML = """\
<html>
<body>
<form>
<input type="hidden" name="bsdsSequence" value="1000"/>
<select name="year">
<option value="2026">2026</option>
<option value="2025">2025</option>
</select>
<input type="submit" name="bsdsSubmit-update-enrol" value="Update Enrolment"/>
<input type="submit" name="bsdsSubmit-view-enrol" value="View Enrolment"/>
</form>
</body>
</html>
"""


COURSES_HTML = """\
<html>
<body>
<table>
<tr>
<th>Course</th>
<th>Description</th>
<th>Status</th>
</tr>
<tr>
<td>COMP6733</td>
<td>IoT Engineering</td>
<td>Enrolled</td>
</tr>
<tr>
<td>COMP9319</td>
<td>Web Data Compression</td>
<td>Enrolled</td>
</tr>
<tr>
<td>COMP9444</td>
<td>Neural Networks</td>
<td>Enrolled</td>
</tr>
</table>
<p>Active Term: 5266 (T2 2026)</p>
<form>
<input type="hidden" name="bsdsSequence" value="1002"/>
<input type="submit" name="bsdsSubmit-view-timetable" value="View Timetable"/>
</form>
</body>
</html>
"""


TIMETABLE_JSON = {
    "courses": [
        {"key": "06642415266T11", "enrolled": True, "registered": True},
    ],
    "classes": [
        {"cn": 11198, "crs": "06642415266T11", "comp": "LEC", "registered": True},
    ],
    "meetings": [
        {
            "cn": 11198,
            "title": "COMP6733 - LEC",
            "descr": "Clancy Aud",
            "day": 1,
            "start": "10:30:00",
            "end": "12:00:00",
            "weeks": "1-5, 7, 9-10",
        },
        {
            "cn": 11199,
            "title": "COMP6733 - TUT",
            "descr": "Bus 201",
            "day": 3,
            "start": "14:00:00",
            "end": "16:00:00",
            "weeks": "1-10",
        },
    ],
}


RESULTS_HTML = """\
<html>
<body>
<table>
<tr>
<th>Course</th>
<th>Description</th>
<th>Units</th>
<th>Mark</th>
<th>Grade</th>
<th>Term</th>
</tr>
<tr>
<td>COMP1511</td>
<td>Programming Fundamentals</td>
<td>6</td>
<td>87</td>
<td>HD</td>
<td>2024 T1</td>
</tr>
<tr>
<td>COMP2521</td>
<td>Data Structures and Algorithms</td>
<td>6</td>
<td>78</td>
<td>DN</td>
<td>2024 T2</td>
</tr>
</table>
</body>
</html>
"""


SEARCH_RESULTS_HTML = """\
<html>
<body>
<table>
<tr>
<th>Class</th>
<th>Section</th>
<th>Component</th>
<th>Day/Time</th>
<th>Location</th>
<th>Status</th>
<th>Enrols</th>
</tr>
<tr>
<td>12345</td>
<td>T13A</td>
<td>LEC</td>
<td>Mon 13:00-15:00</td>
<td>Clancy Aud</td>
<td>Open</td>
<td>120/180</td>
</tr>
</table>
</body>
</html>
"""


# ── Pure helper tests ──────────────────────────────────────────


class TestBsdsHelpers:
    """Tests for BSDS-protocol helper functions."""

    def test_extract_bsds_sequence(self):
        assert _extract_bsds_sequence(YEARS_HTML) == "1000"
        assert _extract_bsds_sequence(COURSES_HTML) == "1002"

    def test_extract_bsds_sequence_missing(self):
        assert _extract_bsds_sequence("<html>No sequence</html>") is None

    def test_extract_current_term(self):
        assert _extract_current_term(COURSES_HTML) == "5266"

    def test_extract_current_term_missing(self):
        assert _extract_current_term(YEARS_HTML) is None

    def test_find_course_codes(self):
        codes = _find_course_codes("COMP6733 COMP9319 MATH1131")
        assert codes == ["COMP6733", "COMP9319", "MATH1131"]

    def test_find_course_codes_deduplicated(self):
        codes = _find_course_codes("COMP6733 and COMP6733 again")
        assert codes == ["COMP6733"]

    def test_find_course_codes_no_match(self):
        assert _find_course_codes("nothing") == []

    def test_day_names_known(self):
        assert DAY_NAMES[1] == "Monday"
        assert DAY_NAMES[5] == "Friday"
        assert DAY_NAMES[7] == "Sunday"

    def test_term_code_to_label_t1(self):
        assert _term_code_to_label("5263") == "T1 2026"

    def test_term_code_to_label_t2(self):
        assert _term_code_to_label("5266") == "T2 2026"

    def test_term_code_to_label_t3(self):
        assert _term_code_to_label("5269") == "T3 2026"

    def test_term_code_to_label_invalid(self):
        # Invalid codes fall through
        assert _term_code_to_label("abc") == "abc"


# ── BsdsClient with mocked Playwright ───────────────────────────


class TestBsdsClientAuth:
    """Tests for BsdsClient.is_authenticated()."""

    def test_not_authenticated_with_no_storage_state(self, isolated_config):
        """Without a storage_state file → not authenticated."""
        with patch("unsw.modules.myunsw._load_storage_state", return_value=None):
            with BsdsClient({}) as client:
                assert client.is_authenticated() is False

    def test_is_authenticated_with_bsds_page(self, isolated_config):
        """200 + bsdsSequence → authenticated."""
        with patch(
            "unsw.modules.myunsw._load_storage_state",
            return_value={"cookies": [], "origins": []},
        ):
            with BsdsClient({}) as client:
                with patch.object(
                    client,
                    "_navigate_sync",
                    return_value=(
                        200,
                        MYUNSW_BASE + "/active/studentClassEnrol/years.xml",
                        YEARS_HTML,
                    ),
                ):
                    assert client.is_authenticated() is True

    def test_is_not_authenticated_on_login_page(self, isolated_config):
        """200 with login page content (no bsdsSequence) → not authenticated."""
        login_html = "<html><title>Login</title>Please log in</html>"
        with patch(
            "unsw.modules.myunsw._load_storage_state",
            return_value={"cookies": [], "origins": []},
        ):
            with BsdsClient({}) as client:
                with patch.object(
                    client,
                    "_navigate_sync",
                    return_value=(200, "https://sso.unsw.edu.au/cas/login", login_html),
                ):
                    assert client.is_authenticated() is False
        with patch(
            "unsw.modules.myunsw._load_storage_state",
            return_value={"cookies": [], "origins": []},
        ):
            with BsdsClient({}) as client:
                with patch.object(
                    client,
                    "_navigate_sync",
                    return_value=(200, MYUNSW_BASE + "/cas/login", login_html),
                ):
                    assert client.is_authenticated() is False


# ── MyUNSWModule wrapper ───────────────────────────────────────


class TestMyUNSWModuleWrapper:
    """Tests for the MyUNSWModule wrapper class."""

    def test_no_storage_state_returns_empty(self, isolated_config):
        """Without storage_state, all data calls return []."""
        with patch("unsw.modules.myunsw._load_storage_state", return_value=None):
            module = MyUNSWModule(isolated_config)
            assert module.get_enrolled_courses() == []
            assert module.get_timetable() == []
            assert module.get_grades() == []
            assert module.search_classes("COMP2521") == []

    def test_search_classes_parses_compound_code(self):
        """'COMP2521' is split into subject='COMP' catalog='2521'."""
        m = re.match(r"^([A-Z]{4})\s*(\d{4})?$", "COMP2521")
        assert m.group(1) == "COMP"
        assert m.group(2) == "2521"

        m = re.match(r"^([A-Z]{4})\s*(\d{4})?$", "COMP")
        assert m.group(1) == "COMP"
        assert m.group(2) is None


class TestKnownTerms:
    def test_known_terms_not_empty(self):
        assert len(KNOWN_TERMS) >= 3

    def test_known_terms_format(self):
        for term in KNOWN_TERMS:
            assert re.match(r"^\d{4}$", term)


# ── HTML parser tests ──────────────────────────────────────────


class TestParseGradesHtml:
    def test_parses_results_table(self):
        grades = _parse_grades_html(RESULTS_HTML)
        assert len(grades) == 2
        comp1511 = next(g for g in grades if g["code"] == "COMP1511")
        assert comp1511["mark"] == "87"
        assert comp1511["grade"] == "HD"
        assert comp1511["term"] == "2024 T1"

    def test_empty_html(self):
        assert _parse_grades_html("<html></html>") == []
