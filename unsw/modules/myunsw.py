"""myUNSW module - course enrolment and student services.

myUNSW exposes a legacy PeopleSoft BSDS (Browser Session Data Sequence) API at
`https://my.unsw.edu.au/active/...`. After Azure AD SSO authentication we get a
``JSESSIONID`` cookie scoped to path ``/active`` which lets us call the BSDS
endpoints directly via plain HTTP and get back structured JSON / HTML data.

BSDS state machine (every page is a state, every action is a submit button):
    GET page            -> extract hidden bsdsSequence
    POST to same URL    -> bsdsSequence + bsdsSubmit-{action} + params
    Server returns 302  -> redirects to next state
    Repeat with new bsdsSequence

Reference: https://github.com/Genius-Cai/myunsw-cli/blob/main/docs/api-reference.md
"""

from __future__ import annotations

import json
import re
import webbrowser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from unsw.auth.myunsw import login_with_cookie
from unsw.config import CONFIG_DIR, Config
from unsw.modules.base import BaseModule
from unsw.utils.output import print_info, print_success, print_warning

MYUNSW_BASE = "https://my.unsw.edu.au"
ACTIVE_BASE = f"{MYUNSW_BASE}/active"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

DAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}
COMPONENT_LABELS = {
    "LEC": "Lecture",
    "TUT": "Tutorial",
    "TLB": "Tutorial-Lab",
    "LAB": "Laboratory",
    "WEB": "Online",
}

# Term codes (most recent first; useful when calling courses.xml without an arg)
KNOWN_TERMS = ["5269", "5266", "5263", "5259", "5256", "5253"]


# ── BSDS helpers ──────────────────────────────────────────────────


def _extract_bsds_sequence(html: str) -> Optional[str]:
    """Extract the bsdsSequence hidden field from a BSDS-rendered page."""
    m = re.search(r'bsdsSequence"\s+value="(\d+)"', html)
    return m.group(1) if m else None


def _extract_current_term(html: str) -> Optional[str]:
    """Try to discover the active term from a courses.xml page."""
    # Look for "Active Term: 5266 (T2 2026)" pattern (text may have HTML tags between)
    m = re.search(
        r"Active Term:.*?(\d{4})\s*\(\s*(T[123]\s*\d{4})\s*\)",
        html,
        re.DOTALL,
    )
    if m:
        return m.group(1)
    # Fallback: look for selected option in term dropdown
    m = re.search(r'<option[^>]+selected[^>]+value="(\d{4})"', html)
    if m:
        return m.group(1)
    return None


def _find_course_codes(text: str) -> list[str]:
    """Find UNSW course codes (4 uppercase letters + 4 digits) in a string."""
    return list(dict.fromkeys(re.findall(r"\b[A-Z]{4}\d{4}\b", text)))


class BsdsClient:
    """Minimal BSDS-protocol client for myUNSW.

    Walks the BSDS state machine to fetch enrolment data, timetable, and grades
    using the JSESSIONID cookie captured during browser login.

    Endpoints used:
        GET  /active/studentClassEnrol/years.xml
        POST /active/studentClassEnrol/years.xml        (update-enrol)
        GET  /active/studentClassEnrol/courses.xml?term=XXXX
        POST /active/studentClassEnrol/courses.xml      (view-timetable)
        GET  /active/studentClassEnrol/timetable.xml?data=classes
        GET  /active/studentClassEnrol/classes.xml?data=classes
        GET  /active/studentResults/reset.xml
        POST /active/studentResults/results.xml         (reload with term)
        GET  /active/studentClassSearch/search.xml
    """

    def __init__(self, cookies: dict[str, str]):
        # Filter to just myUNSW-domain cookies, strip prefix
        self.cookies = {
            k.removeprefix("myunsw_"): v
            for k, v in cookies.items()
            if k.startswith("myunsw_") and v
        }
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            cookies=self.cookies,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self._last_seq: Optional[str] = None
        self._authenticated: Optional[bool] = None

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    def __enter__(self) -> "BsdsClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── Auth verification ───────────────────────────────────────

    def is_authenticated(self) -> bool:
        """Return True if we can access /active/... endpoints."""
        if self._authenticated is not None:
            return self._authenticated
        try:
            resp = self.client.get(f"{ACTIVE_BASE}/studentClassEnrol/years.xml")
            text = resp.text
            self._authenticated = (
                resp.status_code == 200
                and "sso.unsw.edu.au/cas/login" not in str(resp.url).lower()
                and "login.microsoftonline.com" not in str(resp.url).lower()
                and _extract_bsds_sequence(text) is not None
            )
        except Exception:
            self._authenticated = False
        return self._authenticated

    # ── Enrollment walk ─────────────────────────────────────────

    def _walk_to_courses(self, year: str = "2026") -> Optional[str]:
        """Walk the BSDS state machine from years.xml -> courses.xml.

        Returns the courses.xml HTML if successful, None otherwise.
        """
        # 1. GET years.xml
        resp = self.client.get(f"{ACTIVE_BASE}/studentClassEnrol/years.xml")
        if resp.status_code != 200:
            return None
        seq = _extract_bsds_sequence(resp.text)
        if not seq:
            return None

        # 2. POST years.xml (update-enrol) -> 302 to courses.xml
        resp = self.client.post(
            f"{ACTIVE_BASE}/studentClassEnrol/years.xml",
            data={
                "bsdsSequence": seq,
                "year": year,
                "bsdsSubmit-update-enrol": "Update Enrolment",
            },
        )
        if resp.status_code != 200:
            return None
        seq = _extract_bsds_sequence(resp.text)
        if not seq:
            return None
        self._last_seq = seq
        return resp.text

    def _switch_term(self, term: str) -> bool:
        """Switch the active term via courses.xml?term=XXXX AJAX."""
        if not self._last_seq:
            return False
        resp = self.client.get(
            f"{ACTIVE_BASE}/studentClassEnrol/courses.xml",
            params={"term": term},
        )
        return resp.status_code == 200 and resp.text.strip().lower() == "ok"

    def _navigate_to_timetable(self, term: str) -> bool:
        """POST courses.xml with view-timetable action -> lands on timetable state."""
        if not self._last_seq:
            return False
        resp = self.client.post(
            f"{ACTIVE_BASE}/studentClassEnrol/courses.xml",
            data={
                "bsdsSequence": self._last_seq,
                "term": term,
                "bsdsSubmit-view-timetable": "View Timetable",
            },
        )
        if resp.status_code != 200:
            return False
        seq = _extract_bsds_sequence(resp.text)
        if not seq:
            return False
        self._last_seq = seq
        return True

    # ── Public API: courses ────────────────────────────────────

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Get list of currently enrolled courses via the BSDS courses.xml HTML."""
        if not self.is_authenticated():
            return []
        html = self._walk_to_courses()
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        courses: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Detect the term once at the page level (it's shown in a header
        # paragraph, not inside each row)
        page_term = _extract_current_term(html)
        if page_term:
            # Convert code like '5266' to 'T2 2026' label.
            # Term code format: 5YTT where YY is year (last 2 digits) and
            # TT is term digit (3=T1, 6=T2, 9=T3).
            try:
                term_year = 2000 + int(page_term[1:3])
                term_digit = int(page_term[3])
                # Map 3/6/9 → T1/T2/T3
                term_index = (term_digit // 3) if term_digit in (3, 6, 9) else term_digit
                term_label = f"T{term_index} {term_year}"
            except (ValueError, IndexError):
                term_label = page_term
        else:
            term_label = ""

        # Strategy 1: parse the enrolment table. courses.xml renders each
        # enrolled course as a row with course code, title, status, etc.
        for row in soup.select("table tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) < 2:
                continue
            # Find a course code in the row text
            row_text = " ".join(cells)
            codes = _find_course_codes(row_text)
            if not codes:
                continue
            code = codes[0]
            if code in seen:
                continue
            seen.add(code)
            # Extract course name (usually the second cell)
            name = cells[1] if len(cells) > 1 and cells[1] != code else ""
            # Filter out non-course rows (e.g. "Term", "Year")
            if not name or len(name) < 3:
                continue
            courses.append(
                {
                    "code": code,
                    "name": name,
                    "term": term_label,
                    "status": "Enrolled",
                }
            )

        # Strategy 2: fall back to text-scan if table parsing found nothing
        if not courses:
            full_text = soup.get_text(" ", strip=True)
            for code in _find_course_codes(full_text):
                # Try to extract a name near the code
                m = re.search(
                    rf"{re.escape(code)}\s*[-:–—]?\s*([A-Za-z][A-Za-z0-9 &/'\-]{{3,80}})",
                    full_text,
                )
                name = m.group(1).strip().rstrip(",.") if m else code
                courses.append(
                    {
                        "code": code,
                        "name": name,
                        "term": term_label,
                        "status": "Enrolled",
                    }
                )

        return courses

    def get_active_term(self) -> Optional[str]:
        """Discover the active term code (e.g. '5266') for the current user."""
        if not self.is_authenticated():
            return None
        html = self._walk_to_courses()
        if not html:
            return None
        return _extract_current_term(html)

    # ── Public API: timetable ───────────────────────────────────

    def get_timetable_json(
        self, term: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Navigate to timetable state and call ?data=classes JSON API.

        Returns the parsed JSON dict (with 'courses', 'classes', 'meetings')
        or None if it could not be retrieved.
        """
        if not self.is_authenticated():
            return None
        if not self._walk_to_courses():
            return None
        if term is None:
            term = self.get_active_term()
        if term is None:
            term = KNOWN_TERMS[0]
        if not self._switch_term(term):
            return None
        if not self._navigate_to_timetable(term):
            return None
        # Now we're in ENR2.TTBL state; the JSON API is available
        resp = self.client.get(
            f"{ACTIVE_BASE}/studentClassEnrol/timetable.xml",
            params={"data": "classes"},
        )
        if resp.status_code != 200:
            return None
        try:
            return resp.json()
        except Exception:
            return None

    def get_timetable(self, term: Optional[str] = None) -> list[dict[str, Any]]:
        """Get personal class timetable as a list of meeting dicts."""
        data = self.get_timetable_json(term=term)
        if not data:
            return []

        meetings = data.get("meetings", [])
        meetings = data.get("meetings", [])
        classes = data.get("classes", [])
        # Build a lookup from class number to course key
        class_to_course = {cl.get("cn"): cl.get("crs") for cl in classes}

        result: list[dict[str, Any]] = []
        for m in meetings:
            cn = m.get("cn")
            course_key = class_to_course.get(cn, "")

            title = m.get("title", "")
            # Title is like "COMM1100 - LEC" or "COMP6733 - LEC" — extract code
            code_match = re.match(r"([A-Z]{4}\d{4})", title)
            code = code_match.group(1) if code_match else ""

            day_num = m.get("day", 0)
            day = DAY_NAMES.get(day_num, str(day_num)) if day_num else ""

            # Pull out component
            comp_match = re.search(r"-\s*([A-Z]+)\s*$", title)
            component = comp_match.group(1) if comp_match else ""
            activity = COMPONENT_LABELS.get(component, component)

            result.append(
                {
                    "course": code,
                    "cn": cn,
                    "activity": activity,
                    "component": component,
                    "section": str(cn),
                    "day": day,
                    "start": m.get("start", ""),
                    "end": m.get("end", ""),
                    "time": f"{m.get('start', '')}-{m.get('end', '')}",
                    "location": m.get("descr", ""),
                    "weeks": m.get("weeks", ""),
                    "title": title,
                }
            )

        return result

    # ── Public API: class search ────────────────────────────────

    def search_classes(
        self, subject: str, catalog: str = "", term: str = "5266"
    ) -> list[dict[str, Any]]:
        """Search for available classes by subject code (e.g. 'COMP').

        Returns a list of class dicts with class_nbr, section, activity,
        days, time, status, enrols.
        """
        # 1. GET reset.xml to prime the search form and verify auth
        resp = self.client.get(f"{ACTIVE_BASE}/studentClassSearch/reset.xml")
        if resp.status_code != 200:
            return []
        # If we got bounced to CAS login, no auth
        if "sso.unsw.edu.au/cas/login" in str(resp.url).lower():
            return []
        seq = _extract_bsds_sequence(resp.text)
        if not seq:
            return []

        # 2. POST search.xml with search action
        data = {
            "bsdsSequence": seq,
            "term": term,
            "subject": subject.upper(),
            "bsdsSubmit-search": "Search",
        }
        if catalog:
            data["catalogNbr"] = catalog

        resp = self.client.post(
            f"{ACTIVE_BASE}/studentClassSearch/search.xml", data=data
        )
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        classes: list[dict[str, Any]] = []

        # Parse result rows. The search results table has columns like:
        # Class Nbr | Section | Component | Day/Time | Location | Status | Enrols
        for row in soup.select("table tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            # Heuristic: the first cell should be a number (class nbr)
            if not cells[0].strip().isdigit():
                continue
            class_nbr = cells[0].strip()
            entry: dict[str, Any] = {
                "class_nbr": class_nbr,
                "section": cells[1] if len(cells) > 1 else "",
                "activity": cells[2] if len(cells) > 2 else "",
                "day_time": cells[3] if len(cells) > 3 else "",
                "location": cells[4] if len(cells) > 4 else "",
                "status": cells[5] if len(cells) > 5 else "",
                "enrols": cells[6] if len(cells) > 6 else "",
            }
            classes.append(entry)

        return classes

    # ── Public API: grades ──────────────────────────────────────

    def get_grades(self, term: Optional[str] = None) -> list[dict[str, Any]]:
        """Get grades for a single term.

        If term is None, returns grades for the current (default) term.
        """
        # Prime: GET reset.xml (also acts as auth check)
        resp = self.client.get(f"{ACTIVE_BASE}/studentResults/reset.xml")
        if resp.status_code != 200:
            return []
        if "sso.unsw.edu.au/cas/login" in str(resp.url).lower():
            return []
        seq = _extract_bsds_sequence(resp.text)
        if not seq:
            return []

        data: dict[str, str] = {"bsdsSequence": seq}
        if term:
            data["term"] = term
            data["bsdsSubmit-reload"] = "Go"

        resp = self.client.post(f"{ACTIVE_BASE}/studentResults/results.xml", data=data)
        if resp.status_code != 200:
            return []

        return _parse_grades_html(resp.text)

    def get_all_grades(self, terms: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Get grades for multiple terms (default: known recent terms)."""
        if terms is None:
            terms = KNOWN_TERMS
        all_grades: list[dict[str, Any]] = []
        for term in terms:
            grades = self.get_grades(term=term)
            if grades:
                all_grades.extend(grades)
        return all_grades

    # ── Public API: personal info ───────────────────────────────

    def get_address(self) -> list[dict[str, str]]:
        """Get saved addresses."""
        return self._fetch_simple_bsds_page("studentAddress", "reset.xml")

    def get_phone(self) -> list[dict[str, str]]:
        """Get saved phone numbers."""
        return self._fetch_simple_bsds_page("studentPhone", "reset.xml")

    def get_email(self) -> list[dict[str, str]]:
        """Get saved email addresses."""
        return self._fetch_simple_bsds_page("studentEmail", "reset.xml")

    def _fetch_simple_bsds_page(self, module: str, entry: str) -> list[dict[str, str]]:
        """Fetch a simple BSDS read-only page and return rows as dicts."""
        if not self.is_authenticated():
            return []
        resp = self.client.get(f"{ACTIVE_BASE}/{module}/{entry}")
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        rows: list[dict[str, str]] = []
        for table in soup.select("table"):
            headers = [th.get_text(strip=True) for th in table.select("tr th")]
            if not headers:
                continue
            for tr in table.select("tr")[1:]:
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if len(cells) != len(headers):
                    continue
                rows.append(dict(zip(headers, cells)))
        return rows


def _parse_grades_html(html: str) -> list[dict[str, Any]]:
    """Parse the studentResults/results.xml HTML for course grades.

    The BSDS results page renders a table with columns like:
        Course | Description | Units | Mark | Grade | Term
    but the exact ordering can vary. We use header-based column detection
    when possible and fall back to heuristics.
    """
    soup = BeautifulSoup(html, "html.parser")
    grades: list[dict[str, Any]] = []

    # Known UNSW grade codes
    GRADE_CODES = {"HD", "DN", "CR", "PS", "FL", "AF", "PE", "WD", "AS", "EC"}

    # Try to detect column layout from the table header
    for table in soup.select("table"):
        header_cells = [th.get_text(strip=True).lower() for th in table.select("tr th")]
        if not header_cells:
            continue
        # If this table has a 'Course' or 'Mark' header, it's likely the grades table
        if not any(kw in " ".join(header_cells) for kw in ("course", "mark", "grade")):
            continue

        col_index = {name: i for i, name in enumerate(header_cells)}

        for tr in table.select("tr")[1:]:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(cells) != len(header_cells):
                continue

            entry: dict[str, Any] = {}

            # Extract course code from any cell that looks like one
            for cell in cells:
                codes = _find_course_codes(cell)
                if codes:
                    entry["code"] = codes[0]
                    break

            if "code" not in entry:
                continue

            # Map known columns
            for key in ("description", "name", "title"):
                idx = col_index.get(key)
                if idx is not None and idx < len(cells):
                    entry["name"] = cells[idx]
                    break

            for key in ("units", "credits", "credit"):
                idx = col_index.get(key)
                if idx is not None and idx < len(cells):
                    entry["units"] = cells[idx]
                    break

            for key in ("mark", "score", "raw mark"):
                idx = col_index.get(key)
                if idx is not None and idx < len(cells):
                    entry["mark"] = cells[idx]
                    break

            for key in ("grade", "final grade", "result"):
                idx = col_index.get(key)
                if idx is not None and idx < len(cells):
                    entry["grade"] = cells[idx].upper()
                    break

            for key in ("term", "teaching period"):
                idx = col_index.get(key)
                if idx is not None and idx < len(cells):
                    entry["term"] = cells[idx]
                    break

            grades.append(entry)

    # Heuristic fallback if header-based parsing found nothing
    if not grades:
        for row in soup.select("table tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            code = None
            for cell in cells:
                codes = _find_course_codes(cell)
                if codes:
                    code = codes[0]
                    break
            if not code:
                continue
            entry = {"code": code}
            nums = [c for c in cells if re.match(r"^\d{1,3}(\.\d+)?$", c)]
            letter_grades = [c for c in cells if c.upper() in GRADE_CODES]
            if nums:
                entry["mark"] = nums[-1]  # last numeric is usually the mark
            if letter_grades:
                entry["grade"] = letter_grades[0]
            grades.append(entry)

    return grades


# ── Module wrapper ───────────────────────────────────────────────


class MyUNSWModule(BaseModule):
    """Access myUNSW - course enrolment, timetable, grades, and student services."""

    name = "myunsw"
    description = "UNSW myUNSW - course enrolment and student services"

    def __init__(self, config: Config, client=None):
        self.config = config
        cookie_client = login_with_cookie(config)
        super().__init__(client=cookie_client or client)
        self._bsds: Optional[BsdsClient] = None

    def _get_bsds(self) -> Optional[BsdsClient]:
        """Return a lazy-initialized BSDS client, or None if not authed."""
        if self._bsds is not None:
            return self._bsds
        if not self.client:
            print_info(
                "myUNSW not logged in. Run: unsw login --platform myunsw --browser"
            )
            return None
        saved = self.config.load_cookies()
        myunsw_cookies = {k: v for k, v in saved.items() if k.startswith("myunsw_")}
        if not myunsw_cookies:
            print_info(
                "myUNSW cookies missing. Run: unsw login --platform myunsw --browser"
            )
            return None
        self._bsds = BsdsClient(myunsw_cookies)
        return self._bsds

    # ── Enrolled courses ────────────────────────────────────────

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Get list of currently enrolled courses."""
        bsds = self._get_bsds()
        if not bsds:
            return []
        return bsds.get_enrolled_courses()

    # ── Personal timetable ──────────────────────────────────────

    def get_timetable(self) -> list[dict[str, Any]]:
        """Get personal class timetable from myUNSW enrolment data."""
        bsds = self._get_bsds()
        if not bsds:
            return []
        return bsds.get_timetable()

    # ── Class search ────────────────────────────────────────────

    def search_classes(self, query: str) -> list[dict[str, Any]]:
        """Search for available classes.

        Query may be:
          - "COMP2521" (subject + catalog)
          - "COMP" (subject only — returns all COMP courses for the term)
        """
        bsds = self._get_bsds()
        if not bsds:
            return []

        m = re.match(r"^([A-Z]{4})\s*(\d{4})?$", query.strip().upper())
        if not m:
            print_info(f"Invalid course code: {query}")
            return []
        subject = m.group(1)
        catalog = m.group(2) or ""
        return bsds.search_classes(subject=subject, catalog=catalog)

    # ── Grades ──────────────────────────────────────────────────

    def get_grades(self, term: Optional[str] = None) -> list[dict[str, Any]]:
        """Get grades for a term, or current term if not specified."""
        bsds = self._get_bsds()
        if not bsds:
            return []
        if term:
            return bsds.get_grades(term=term)
        # Try current term first, then fall back to known terms
        return bsds.get_all_grades()

    # ── Browser fallbacks ───────────────────────────────────────

    def open_enrolment_page(self) -> str:
        """Open the myUNSW enrolment page in the user's browser."""
        url = f"{ACTIVE_BASE}/studentClassEnrol/years.xml"
        webbrowser.open(url)
        print_info(f"Opened {url} in your browser.")
        print_info("Navigate the BSDS flow to enrol, drop, or swap classes.")
        return url

    def open_class_search(self, course_code: str = "") -> str:
        """Open the myUNSW class search page in the user's browser."""
        url = f"{ACTIVE_BASE}/studentClassSearch/search.xml"
        webbrowser.open(url)
        print_info(f"Opened {url} in your browser.")
        if course_code:
            print_info(f"Search for course: {course_code.upper()}")
        return url

    def open_timetable_page(self) -> str:
        """Open the myUNSW class timetable page in the user's browser."""
        url = f"{ACTIVE_BASE}/studentClassEnrol/timetable.xml"
        webbrowser.open(url)
        print_info(f"Opened myUNSW class timetable in your browser.")
        return url

    def open_grades_page(self) -> str:
        """Open the myUNSW grades page in the user's browser."""
        url = f"{ACTIVE_BASE}/studentResults/results.xml"
        webbrowser.open(url)
        print_info(f"Opened myUNSW grades page in your browser.")
        return url

    def open_personal_info(self, section: str = "address") -> str:
        """Open a personal info page in the user's browser.

        section: address, phone, email, name, emergency
        """
        page_map = {
            "address": "studentAddress/reset.xml",
            "phone": "studentPhone/reset.xml",
            "email": "studentEmail/reset.xml",
            "name": "preferredName/reset.xml",
            "emergency": "emergencyContact/reset.xml",
        }
        path = page_map.get(section.lower())
        if not path:
            print_info(f"Unknown section '{section}'. Valid: {', '.join(page_map)}")
            return ""
        url = f"{ACTIVE_BASE}/{path}"
        webbrowser.open(url)
        print_info(f"Opened myUNSW {section} page in your browser.")
        return url
