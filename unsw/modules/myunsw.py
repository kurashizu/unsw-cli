"""myUNSW module - course enrolment and student services.

myUNSW exposes legacy PeopleSoft BSDS (Browser Session Data Sequence) endpoints at
``https://my.unsw.edu.au/active/...``. The BSDS server strictly enforces cookie
domain/path scoping — for example, the ``JSESSIONID`` cookie must be sent with
``path=/active`` for ``/active/...`` URLs to work. Plain HTTP libraries like
``httpx`` don't handle this nuance as well as a real browser, so we drive a
headless Playwright browser with the saved storage_state and parse the rendered
HTML.

BSDS state machine (every page is a state, every action is a submit button):
    GET page            -> extract hidden bsdsSequence
    POST to same URL    -> bsdsSequence + bsdsSubmit-{action} + params
    Server returns 302  -> redirects to next state
    Repeat with new bsdsSequence

Reference: https://github.com/Genius-Cai/myunsw-cli/blob/main/docs/api-reference.md
"""

from __future__ import annotations

import asyncio
import json
import re
import webbrowser
from pathlib import Path
from typing import Any, Optional

from bs4 import BeautifulSoup

from unsw.auth.myunsw import login_with_cookie
from unsw.config import CONFIG_DIR, Config
from unsw.modules.base import BaseModule
from unsw.utils.output import print_info, print_success, print_warning

MYUNSW_BASE = "https://my.unsw.edu.au"
ACTIVE_BASE = f"{MYUNSW_BASE}/active"
STORAGE_STATE_PATH = CONFIG_DIR / "myunsw_storage.json"

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
    m = re.search(
        r"Active Term:.*?(\d{4})\s*\(\s*(T[123]\s*\d{4})\s*\)",
        html,
        re.DOTALL,
    )
    if m:
        return m.group(1)
    m = re.search(r'<option[^>]+selected[^>]+value="(\d{4})"', html)
    if m:
        return m.group(1)
    return None


def _find_course_codes(text: str) -> list[str]:
    """Find UNSW course codes (4 uppercase letters + 4 digits) in a string."""
    return list(dict.fromkeys(re.findall(r"\b[A-Z]{4}\d{4}\b", text)))


def _load_storage_state() -> Optional[dict[str, Any]]:
    """Load the saved Playwright storage state, if present."""
    if not STORAGE_STATE_PATH.exists():
        return None
    try:
        with open(STORAGE_STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _term_code_to_label(code: str) -> str:
    """Convert a term code like '5266' to a human label 'T2 2026'."""
    try:
        term_year = 2000 + int(code[1:3])
        term_digit = int(code[3])
        term_index = (term_digit // 3) if term_digit in (3, 6, 9) else term_digit
        return f"T{term_index} {term_year}"
    except (ValueError, IndexError):
        return code


def _run_async(coro):
    """Run an async coroutine from sync code, even if there's already a loop."""
    try:
        # Are we already inside an event loop?
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # We're inside a loop — need to bridge
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(asyncio.run, coro)
        return future.result()


# ── BSDS client (Playwright-based) ────────────────────────────────


class BsdsClient:
    """BSDS-protocol client for myUNSW.

    Drives a headless Playwright browser with the saved storage_state. The
    browser handles cookie domain/path scoping correctly, which is critical
    for the BSDS server (it requires ``JSESSIONID`` scoped to ``path=/active``).
    """

    def __init__(self, cookies: dict[str, str]):
        # cookies parameter is kept for backwards-compat / API parity but
        # we now rely on the saved storage_state instead.
        self.cookies = cookies
        self._authenticated: Optional[bool] = None

    def close(self) -> None:
        pass

    def __enter__(self) -> "BsdsClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── Playwright-driven navigation ─────────────────────────────

    async def _navigate_to(
        self, url: str, wait_until: str = "domcontentloaded"
    ) -> tuple[Optional[int], Optional[str], Optional[str]]:
        """Navigate to a URL using a fresh Playwright context loaded with
        the saved storage_state. Returns (status_code, final_url, html)."""
        from playwright.async_api import async_playwright

        storage_state = _load_storage_state()
        if not storage_state:
            return None, None, None

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception:
                return None, None, None
            try:
                context = await browser.new_context(
                    storage_state=storage_state,
                    user_agent=USER_AGENT,
                )
                page = await context.new_page()
                resp = await page.goto(url, wait_until=wait_until, timeout=20000)
                status = resp.status if resp else None
                final_url = page.url
                html = await page.content()
                await context.close()
                await browser.close()
                return status, final_url, html
            except Exception:
                try:
                    await browser.close()
                except Exception:
                    pass
                return None, None, None

    async def _post_form(
        self, url: str, data: dict[str, str]
    ) -> tuple[Optional[int], Optional[str], Optional[str]]:
        """POST form data to a URL using Playwright's request context.

        Uses the browser context's request context (which carries the
        saved cookies) to POST form-encoded data. Returns (status, final_url, html).
        """
        from playwright.async_api import async_playwright

        storage_state = _load_storage_state()
        if not storage_state:
            return None, None, None

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception:
                return None, None, None
            try:
                context = await browser.new_context(
                    storage_state=storage_state,
                    user_agent=USER_AGENT,
                )
                # Use the context's request context to POST with proper cookies
                response = await context.request.post(url, form=data)
                status = response.status
                final_url = response.url
                html = await response.text()
                await context.close()
                await browser.close()
                return status, final_url, html
            except Exception:
                try:
                    await browser.close()
                except Exception:
                    pass
                return None, None, None

    def _navigate_sync(
        self, url: str
    ) -> tuple[Optional[int], Optional[str], Optional[str]]:
        return _run_async(self._navigate_to(url))

    def _post_sync(
        self, url: str, data: dict[str, str]
    ) -> tuple[Optional[int], Optional[str], Optional[str]]:
        return _run_async(self._post_form(url, data))

    # ── Auth verification ───────────────────────────────────────

    def is_authenticated(self) -> bool:
        """Return True if we can access /active/... endpoints."""
        if self._authenticated is not None:
            return self._authenticated
        if _load_storage_state() is None:
            self._authenticated = False
            return False
        status, final_url, html = self._navigate_sync(
            f"{ACTIVE_BASE}/studentClassEnrol/years.xml"
        )
        self._authenticated = (
            status == 200
            and final_url is not None
            and "sso.unsw.edu.au/cas/login" not in final_url.lower()
            and "login.microsoftonline" not in final_url.lower()
            and html is not None
            and _extract_bsds_sequence(html) is not None
        )
        return self._authenticated

    # ── BSDS walk helpers ───────────────────────────────────────

    def _walk_to_courses(self, year: str = "2026") -> Optional[str]:
        """Walk BSDS state machine years.xml -> courses.xml.

        Returns courses.xml HTML or None.
        """
        # 1. GET years.xml
        status, final_url, html = self._navigate_sync(
            f"{ACTIVE_BASE}/studentClassEnrol/years.xml"
        )
        if status != 200 or not html:
            return None
        seq = _extract_bsds_sequence(html)
        if not seq:
            return None

        # 2. POST years.xml (update-enrol) -> 302 to courses.xml
        status, final_url, html = self._post_sync(
            f"{ACTIVE_BASE}/studentClassEnrol/years.xml",
            {
                "bsdsSequence": seq,
                "year": year,
                "bsdsSubmit-update-enrol": "Update Enrolment",
            },
        )
        if status != 200 or not html:
            return None
        seq = _extract_bsds_sequence(html)
        if not seq:
            return None
        return html

    def _switch_term(self, term: str) -> bool:
        """Switch the active term via courses.xml?term=XXXX AJAX."""
        _, _, html = self._navigate_sync(
            f"{ACTIVE_BASE}/studentClassEnrol/courses.xml?term={term}"
        )
        return html is not None and html.strip().lower() == "ok"

    def _navigate_to_timetable(self, term: str) -> Optional[str]:
        """POST courses.xml with view-timetable -> land in timetable state."""
        # First switch term
        if not self._switch_term(term):
            return None
        # GET courses.xml again to get a fresh bsdsSequence
        _, _, html = self._navigate_sync(f"{ACTIVE_BASE}/studentClassEnrol/courses.xml")
        if not html:
            return None
        seq = _extract_bsds_sequence(html)
        if not seq:
            return None
        # POST courses.xml (view-timetable) -> 302 to timetable.xml
        status, final_url, html = self._post_sync(
            f"{ACTIVE_BASE}/studentClassEnrol/courses.xml",
            {
                "bsdsSequence": seq,
                "term": term,
                "bsdsSubmit-view-timetable": "View Timetable",
            },
        )
        if status != 200 or not html:
            return None
        return html

    # ── Public API: courses ─────────────────────────────────────

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Get list of currently enrolled courses."""
        if not self.is_authenticated():
            return []
        html = self._walk_to_courses()
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        courses: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Detect the term once at the page level
        page_term = _extract_current_term(html)
        term_label = _term_code_to_label(page_term) if page_term else ""

        for row in soup.select("table tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) < 2:
                continue
            row_text = " ".join(cells)
            codes = _find_course_codes(row_text)
            if not codes:
                continue
            code = codes[0]
            if code in seen:
                continue
            seen.add(code)
            name = cells[1] if len(cells) > 1 and cells[1] != code else ""
            if not name or len(name) < 3:
                continue
            courses.append(
                {"code": code, "name": name, "term": term_label, "status": "Enrolled"}
            )

        if not courses:
            full_text = soup.get_text(" ", strip=True)
            for code in _find_course_codes(full_text):
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

    def get_enrolment_blocker(self) -> Optional[str]:
        """If the user is blocked from enrolment (e.g. overdue fees), return
        a short description of the blocker. Otherwise return None.

        myUNSW shows an "Action Item(s)" page when the user can't access
        enrolment features. We detect this by navigating to years.xml
        and checking if we end up on actionItems.xml.
        """
        if _load_storage_state() is None:
            return None
        status, final_url, html = self._navigate_sync(
            f"{ACTIVE_BASE}/studentClassEnrol/years.xml"
        )
        if not html:
            return None
        if "actionItems" not in (final_url or "").lower() and "Action Item" not in html:
            return None
        # Parse the action items page
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        # Extract the reason (after "outstanding item(s):")
        m = re.search(r"outstanding item\(s\):(.*?)(?:\.\s|\Z)", text, re.DOTALL)
        if m:
            # Get the first reason line
            reason = m.group(1).strip().split("\n")[0].strip()[:200]
            return reason
        return "Outstanding action items (see myUNSW Action Items page)"

    # ── Public API: timetable ───────────────────────────────────

    def get_timetable_json(
        self, term: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Navigate to timetable state and call ?data=classes JSON API."""
        if not self.is_authenticated():
            return None
        if not self._walk_to_courses():
            return None
        if term is None:
            term = self.get_active_term()
        if term is None:
            term = KNOWN_TERMS[0]
        # Navigate to timetable state
        if not self._navigate_to_timetable(term):
            return None
        # Now in ENR2.TTBL state — fetch the JSON API
        # We need to do this via httpx with proper cookie handling because
        # the JSON endpoint requires correct Cookie header (not browser storage).
        # But we need to extract the right cookies first.
        cookies = self._extract_active_cookies()
        if not cookies:
            return None
        try:
            import httpx

            client = httpx.Client(timeout=15.0, cookies=cookies)
            client.headers.update({"User-Agent": USER_AGENT})
            resp = client.get(
                f"{ACTIVE_BASE}/studentClassEnrol/timetable.xml?data=classes"
            )
            client.close()
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception:
            return None

    def _extract_active_cookies(self) -> dict[str, str]:
        """Extract the JSESSIONID and other /active cookies from saved state."""
        state = _load_storage_state()
        if not state:
            return {}
        cookies: dict[str, str] = {}
        for c in state.get("cookies", []):
            path = c.get("path", "/")
            domain = c.get("domain", "")
            # We need /active cookies on my.unsw.edu.au
            if path == "/active" and "my.unsw.edu.au" in domain:
                cookies[c["name"]] = c["value"]
        return cookies

    def get_timetable(self, term: Optional[str] = None) -> list[dict[str, Any]]:
        """Get personal class timetable as a list of meeting dicts."""
        data = self.get_timetable_json(term=term)
        if not data:
            return []

        meetings = data.get("meetings", [])
        classes = data.get("classes", [])
        class_to_course = {cl.get("cn"): cl.get("crs") for cl in classes}

        result: list[dict[str, Any]] = []
        for m in meetings:
            cn = m.get("cn")
            course_key = class_to_course.get(cn, "")

            title = m.get("title", "")
            code_match = re.match(r"([A-Z]{4}\d{4})", title)
            code = code_match.group(1) if code_match else ""

            day_num = m.get("day", 0)
            day = DAY_NAMES.get(day_num, str(day_num)) if day_num else ""

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
        """Search for available classes by subject code (e.g. 'COMP')."""
        if not self.is_authenticated():
            return []

        # 1. GET reset.xml to prime the search form
        status, final_url, html = self._navigate_sync(
            f"{ACTIVE_BASE}/studentClassSearch/reset.xml"
        )
        if status != 200 or not html:
            return []
        if final_url and "sso.unsw.edu.au/cas/login" in final_url.lower():
            return []
        seq = _extract_bsds_sequence(html)
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

        status, final_url, html = self._post_sync(
            f"{ACTIVE_BASE}/studentClassSearch/search.xml", data
        )
        if status != 200 or not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        classes: list[dict[str, Any]] = []
        for row in soup.select("table tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) < 4:
                continue
            if not cells[0].strip().isdigit():
                continue
            classes.append(
                {
                    "class_nbr": cells[0].strip(),
                    "section": cells[1] if len(cells) > 1 else "",
                    "activity": cells[2] if len(cells) > 2 else "",
                    "day_time": cells[3] if len(cells) > 3 else "",
                    "location": cells[4] if len(cells) > 4 else "",
                    "status": cells[5] if len(cells) > 5 else "",
                    "enrols": cells[6] if len(cells) > 6 else "",
                }
            )
        return classes

    # ── Public API: grades ──────────────────────────────────────

    def get_grades(self, term: Optional[str] = None) -> list[dict[str, Any]]:
        """Get grades for a term."""
        if not self.is_authenticated():
            return []
        status, final_url, html = self._navigate_sync(
            f"{ACTIVE_BASE}/studentResults/reset.xml"
        )
        if status != 200 or not html:
            return []
        if final_url and "sso.unsw.edu.au/cas/login" in final_url.lower():
            return []
        seq = _extract_bsds_sequence(html)
        if not seq:
            return []

        data: dict[str, str] = {"bsdsSequence": seq}
        if term:
            data["term"] = term
            data["bsdsSubmit-reload"] = "Go"

        status, final_url, html = self._post_sync(
            f"{ACTIVE_BASE}/studentResults/results.xml", data
        )
        if status != 200 or not html:
            return []
        return _parse_grades_html(html)

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


# ── HTML parsers ──────────────────────────────────────────────────


def _parse_grades_html(html: str) -> list[dict[str, Any]]:
    """Parse the studentResults/results.xml HTML for course grades.

    Strategy: find the column layout (Course | Description | Session | Units
    | Mark | Grade) anywhere on the page, then scan subsequent tables/rows
    for matching data.
    """
    soup = BeautifulSoup(html, "html.parser")
    grades: list[dict[str, Any]] = []
    GRADE_CODES = {"HD", "DN", "CR", "PS", "FL", "AF", "PE", "WD", "AS", "EC"}

    # First, find the column layout (look for a row that has "Course" and "Grade" headers).
    # The headers may be in <th> OR in <td> elements with bold text.
    col_index: dict[str, int] = {}
    for tr in soup.select("tr"):
        # Try <th> first
        headers = [th.get_text(strip=True) for th in tr.find_all("th")]
        if not headers:
            # Then try the first <td> row that has a Course-like structure
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            # Detect: cells[0] is "Course" and len matches 6 (Course|Description|Session|Units Taken|Mark|Grade)
            if (
                len(cells) >= 4
                and cells[0] == "Course"
                and any(
                    c in ("Mark", "Grade", "Description", "Description") for c in cells
                )
            ):
                headers = cells
        if not headers:
            continue
        header_text = " ".join(headers).lower()
        if "course" in header_text and (
            "grade" in header_text or "mark" in header_text
        ):
            col_index = {h.lower(): i for i, h in enumerate(headers)}
            break

    # Filter out rows whose first cell is a non-data mega-cell (e.g.
    # the "View results for: ..." summary that contains all text in one <td>).
    # Data rows have one <td> per column matching the column layout.
    seen_codes: set[str] = set()
    for tr in soup.select("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        # Find a course code
        code = None
        for cell in cells:
            codes = _find_course_codes(cell)
            if codes:
                code = codes[0]
                break
        if not code:
            continue
        # If the row has way more cells than the column layout, it's a
        # summary/navigation row, not a data row.
        if col_index and len(cells) > len(col_index) + 2:
            continue
        # If the first cell is very long (a mega-cell summary), skip it
        if cells and len(cells[0]) > 100:
            continue
        # Dedupe (don't pick up the same course twice)
        if code in seen_codes:
            continue
        seen_codes.add(code)
        entry: dict[str, Any] = {"code": code}

        for key in ("description", "name", "title"):
            idx = col_index.get(key)
            if idx is not None and idx < len(cells):
                entry["name"] = cells[idx]
                break
        for key in ("session", "term", "teaching period"):
            idx = col_index.get(key)
            if idx is not None and idx < len(cells):
                entry["term"] = cells[idx]
                break
        for key in (
            "units taken",
            "units",
            "credits",
            "credit",
        ):
            idx = col_index.get(key)
            if idx is not None and idx < len(cells):
                entry["units"] = cells[idx]
                break
        for key in ("mark", "score", "raw mark"):
            idx = col_index.get(key)
            if idx is not None and idx < len(cells):
                val = cells[idx].strip()
                if val:
                    entry["mark"] = val
                break
        for key in ("grade", "final grade", "result"):
            idx = col_index.get(key)
            if idx is not None and idx < len(cells):
                val = cells[idx].strip()
                if val:
                    entry["grade"] = val.upper()
                break
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
        # Check storage_state first
        if _load_storage_state() is None:
            print_info(
                "myUNSW not logged in. Run: unsw login --platform myunsw --browser"
            )
            return None
        saved = self.config.load_cookies()
        myunsw_cookies = {k: v for k, v in saved.items() if k.startswith("myunsw_")}
        self._bsds = BsdsClient(myunsw_cookies)
        return self._bsds

    # ── Enrolled courses ────────────────────────────────────────

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Get list of currently enrolled courses."""
        bsds = self._get_bsds()
        if not bsds:
            return []
        result = bsds.get_enrolled_courses()
        if not result:
            # Check whether the user is blocked by outstanding items
            blocker = bsds.get_enrolment_blocker()
            if blocker:
                print_info(f"myUNSW enrolment blocked: {blocker}")
        return result

    # ── Personal timetable ──────────────────────────────────────

    def get_timetable(self) -> list[dict[str, Any]]:
        """Get personal class timetable from myUNSW enrolment data."""
        bsds = self._get_bsds()
        if not bsds:
            return []
        return bsds.get_timetable()

    # ── Class search ────────────────────────────────────────────

    def search_classes(self, query: str) -> list[dict[str, Any]]:
        """Search for available classes by subject code (e.g. 'COMP2521')."""
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
        """Open a personal info page in the user's browser."""
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
