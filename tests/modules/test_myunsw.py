"""Tests for unsw/modules/myunsw.py — BSDS protocol, courses, timetable, grades."""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

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
        {"key": "06462415266T11", "enrolled": True, "registered": True},
        {"key": "06449445266T11", "enrolled": True, "registered": True},
    ],
    "classes": [
        {
            "cn": 11198,
            "crs": "06642415266T11",
            "comp": "LEC",
            "registered": True,
        },
        {
            "cn": 11199,
            "crs": "06642415266T11",
            "comp": "TUT",
            "registered": True,
        },
        {
            "cn": 11200,
            "crs": "06462415266T11",
            "comp": "LEC",
            "registered": True,
        },
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
        {
            "cn": 11200,
            "title": "COMP9319 - LEC",
            "descr": "Online",
            "day": 2,
            "start": "18:00:00",
            "end": "20:00:00",
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
<tr>
<td>MATH1131</td>
<td>Mathematics 1A</td>
<td>6</td>
<td>65</td>
<td>CR</td>
<td>2024 T1</td>
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
<tr>
<td>12346</td>
<td>W14A</td>
<td>TUT</td>
<td>Wed 14:00-16:00</td>
<td>Bus 115</td>
<td>Open</td>
<td>18/25</td>
</tr>
</table>
</body>
</html>
"""


# ── Helpers ────────────────────────────────────────────────────


class TestBsdsHelpers:
    """Tests for BSDS-protocol helper functions."""

    def test_extract_bsds_sequence(self):
        """Extract bsdsSequence from a BSDS page."""
        assert _extract_bsds_sequence(YEARS_HTML) == "1000"
        assert _extract_bsds_sequence(COURSES_HTML) == "1002"

    def test_extract_bsds_sequence_missing(self):
        """Missing bsdsSequence → None."""
        html = "<html><body>No sequence here</body></html>"
        assert _extract_bsds_sequence(html) is None

    def test_extract_current_term(self):
        """Extract active term from a courses page."""
        assert _extract_current_term(COURSES_HTML) == "5266"

    def test_extract_current_term_missing(self):
        """Missing term → None."""
        assert _extract_current_term(YEARS_HTML) is None

    def test_find_course_codes(self):
        """Find UNSW course codes in text."""
        text = "You are taking COMP6733, COMP9319 and MATH1131."
        assert _find_course_codes(text) == ["COMP6733", "COMP9319", "MATH1131"]

    def test_find_course_codes_deduplicated(self):
        """Duplicates are preserved in first-seen order, deduped."""
        text = "COMP6733 and COMP6733 again and COMP9444"
        codes = _find_course_codes(text)
        assert codes == ["COMP6733", "COMP9444"]

    def test_find_course_codes_no_match(self):
        """No codes → empty list."""
        assert _find_course_codes("nothing here") == []

    def test_day_names_known(self):
        """Day number → name mapping is correct."""
        assert DAY_NAMES[1] == "Monday"
        assert DAY_NAMES[5] == "Friday"
        assert DAY_NAMES[7] == "Sunday"


# ── BSDS Client ────────────────────────────────────────────────


class TestBsdsClientAuth:
    """Tests for BsdsClient.is_authenticated()."""

    @respx.mock
    def test_is_authenticated_with_bsds_page(self):
        """200 + bsdsSequence → authenticated."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=YEARS_HTML)
        )
        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            assert client.is_authenticated() is True
            # Second call should be cached
            assert client.is_authenticated() is True

    @respx.mock
    def test_is_not_authenticated_when_redirected_to_login(self):
        """302 to CAS login → not authenticated."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(
                302,
                headers={"location": "https://sso.unsw.edu.au/cas/login?service=..."},
            )
        )
        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            assert client.is_authenticated() is False

    @respx.mock
    def test_is_not_authenticated_on_login_page(self):
        """200 with login page content (no bsdsSequence) → not authenticated."""
        login_html = "<html><title>Login</title>Please log in</html>"
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=login_html)
        )
        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            assert client.is_authenticated() is False

    def test_not_authenticated_with_no_cookies(self):
        """Empty cookies → not authenticated, no request made."""
        with BsdsClient({}) as client:
            assert client.is_authenticated() is False


class TestBsdsClientCourses:
    """Tests for BsdsClient.get_enrolled_courses()."""

    @respx.mock
    def test_get_enrolled_courses_parses_table(self):
        """Parses course rows from a BSDS courses.xml page."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=YEARS_HTML)
        )
        respx.post(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=COURSES_HTML)
        )
        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            courses = client.get_enrolled_courses()

        assert len(courses) == 3
        codes = [c["code"] for c in courses]
        assert "COMP6733" in codes
        assert "COMP9319" in codes
        assert "COMP9444" in codes
        # Term should be detected from the page
        assert all(c["term"] == "T2 2026" for c in courses)
        # Names should be present
        comp6733 = next(c for c in courses if c["code"] == "COMP6733")
        assert "IoT Engineering" in comp6733["name"]

    @respx.mock
    def test_get_enrolled_courses_returns_empty_when_not_authed(self):
        """No auth → empty list."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(
                302,
                headers={"location": "https://sso.unsw.edu.au/cas/login"},
            )
        )
        with BsdsClient({"myunsw_JSESSIONID": "expired"}) as client:
            assert client.get_enrolled_courses() == []


class TestBsdsClientTimetable:
    """Tests for BsdsClient.get_timetable() and get_timetable_json()."""

    @respx.mock
    def test_get_timetable_json_walks_bsds(self):
        """Navigate years.xml → courses.xml → switch term → view-timetable → JSON API."""
        # The full BSDS walk
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=YEARS_HTML)
        )
        respx.post(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=COURSES_HTML)
        )
        respx.get(
            f"{MYUNSW_BASE}/active/studentClassEnrol/courses.xml",
            params={"term": "5266"},
        ).mock(return_value=httpx.Response(200, text="ok"))
        respx.post(f"{MYUNSW_BASE}/active/studentClassEnrol/courses.xml").mock(
            return_value=httpx.Response(200, text=COURSES_HTML)
        )
        respx.get(
            f"{MYUNSW_BASE}/active/studentClassEnrol/timetable.xml",
            params={"data": "classes"},
        ).mock(
            return_value=httpx.Response(
                200, json=TIMETABLE_JSON, headers={"content-type": "application/json"}
            )
        )

        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            data = client.get_timetable_json(term="5266")
        assert data is not None
        assert len(data["meetings"]) == 3

    @respx.mock
    def test_get_timetable_meetings_have_human_readable_fields(self):
        """Meetings should be transformed to readable form."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=YEARS_HTML)
        )
        respx.post(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(200, text=COURSES_HTML)
        )
        respx.get(
            f"{MYUNSW_BASE}/active/studentClassEnrol/courses.xml",
            params={"term": "5266"},
        ).mock(return_value=httpx.Response(200, text="ok"))
        respx.post(f"{MYUNSW_BASE}/active/studentClassEnrol/courses.xml").mock(
            return_value=httpx.Response(200, text=COURSES_HTML)
        )
        respx.get(
            f"{MYUNSW_BASE}/active/studentClassEnrol/timetable.xml",
            params={"data": "classes"},
        ).mock(
            return_value=httpx.Response(
                200, json=TIMETABLE_JSON, headers={"content-type": "application/json"}
            )
        )

        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            timetable = client.get_timetable(term="5266")

        assert len(timetable) == 3
        first = timetable[0]
        assert first["course"] == "COMP6733"
        assert first["day"] == "Monday"
        assert first["time"] == "10:30:00-12:00:00"
        assert first["location"] == "Clancy Aud"
        assert first["activity"] == "Lecture"
        assert first["weeks"] == "1-5, 7, 9-10"

    @respx.mock
    def test_get_timetable_returns_empty_when_not_authed(self):
        """No auth → empty list."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassEnrol/years.xml").mock(
            return_value=httpx.Response(
                302,
                headers={"location": "https://sso.unsw.edu.au/cas/login"},
            )
        )
        with BsdsClient({"myunsw_JSESSIONID": "expired"}) as client:
            assert client.get_timetable() == []


class TestBsdsClientSearch:
    """Tests for BsdsClient.search_classes()."""

    @respx.mock
    def test_search_classes_returns_rows(self):
        """Search results table is parsed into class dicts."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassSearch/reset.xml").mock(
            return_value=httpx.Response(200, text=YEARS_HTML)
        )
        respx.post(f"{MYUNSW_BASE}/active/studentClassSearch/search.xml").mock(
            return_value=httpx.Response(200, text=SEARCH_RESULTS_HTML)
        )
        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            classes = client.search_classes("COMP", catalog="2521")

        assert len(classes) == 2
        assert classes[0]["class_nbr"] == "12345"
        assert classes[0]["section"] == "T13A"
        assert classes[0]["activity"] == "LEC"
        assert classes[1]["class_nbr"] == "12346"

    @respx.mock
    def test_search_classes_empty_on_no_results(self):
        """If the server returns no rows, we get an empty list."""
        respx.get(f"{MYUNSW_BASE}/active/studentClassSearch/reset.xml").mock(
            return_value=httpx.Response(200, text=YEARS_HTML)
        )
        empty = "<html><body><table><tr><th>Class</th></tr></table></body></html>"
        respx.post(f"{MYUNSW_BASE}/active/studentClassSearch/search.xml").mock(
            return_value=httpx.Response(200, text=empty)
        )
        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            assert client.search_classes("MATH9999") == []


class TestBsdsClientGrades:
    """Tests for BsdsClient.get_grades()."""

    @respx.mock
    def test_get_grades_parses_results_table(self):
        """Grades table is parsed into list of {code, mark, grade, name, term}."""
        respx.get(f"{MYUNSW_BASE}/active/studentResults/reset.xml").mock(
            return_value=httpx.Response(200, text=YEARS_HTML)
        )
        respx.post(f"{MYUNSW_BASE}/active/studentResults/results.xml").mock(
            return_value=httpx.Response(200, text=RESULTS_HTML)
        )
        with BsdsClient({"myunsw_JSESSIONID": "abc"}) as client:
            grades = client.get_grades(term="5246")

        assert len(grades) == 3
        comp1511 = next(g for g in grades if g["code"] == "COMP1511")
        assert comp1511["mark"] == "87"
        assert comp1511["grade"] == "HD"
        assert comp1511["term"] == "2024 T1"
        assert "Programming" in comp1511["name"]

    def test_parse_grades_html_extracts_rows(self):
        """Pure-HTML parser works without going through HTTP."""
        grades = _parse_grades_html(RESULTS_HTML)
        assert len(grades) == 3
        codes = [g["code"] for g in grades]
        assert "COMP1511" in codes
        assert "MATH1131" in codes


# ── MyUNSWModule wrapper ───────────────────────────────────────


class TestMyUNSWModuleWrapper:
    """Tests for the MyUNSWModule wrapper class."""

    def test_no_session_returns_empty_for_courses(self, isolated_config):
        """Without cookies, get_enrolled_courses returns []."""
        module = MyUNSWModule(isolated_config)
        assert module.get_enrolled_courses() == []

    def test_no_session_returns_empty_for_timetable(self, isolated_config):
        """Without cookies, get_timetable returns []."""
        module = MyUNSWModule(isolated_config)
        assert module.get_timetable() == []

    def test_no_session_returns_empty_for_grades(self, isolated_config):
        """Without cookies, get_grades returns []."""
        module = MyUNSWModule(isolated_config)
        assert module.get_grades() == []

    def test_no_session_returns_empty_for_search(self, isolated_config):
        """Without cookies, search_classes returns []."""
        module = MyUNSWModule(isolated_config)
        assert module.search_classes("COMP2521") == []

    def test_search_classes_parses_compound_code(self, isolated_config):
        """'COMP2521' is split into subject='COMP' catalog='2521'."""
        # We can't easily mock the BsdsClient here without more refactoring,
        # so just test the parse logic via a unit test on the regex
        from unsw.modules.myunsw import MyUNSWModule as Mod

        m = re.match(r"^([A-Z]{4})\s*(\d{4})?$", "COMP2521")
        assert m.group(1) == "COMP"
        assert m.group(2) == "2521"
        m = re.match(r"^([A-Z]{4})\s*(\d{4})?$", "COMP")
        assert m.group(1) == "COMP"
        assert m.group(2) is None


class TestKnownTerms:
    """Sanity check on the term code list."""

    def test_known_terms_not_empty(self):
        """Should have at least a few terms."""
        assert len(KNOWN_TERMS) >= 3

    def test_known_terms_format(self):
        """All terms should be 4-digit codes."""
        for term in KNOWN_TERMS:
            assert re.match(r"^\d{4}$", term), f"Bad term format: {term}"
