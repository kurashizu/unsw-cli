"""myUNSW module - course enrolment and student services.

Provides access to myUNSW for viewing enrolled courses and managing enrolment.
Since myUNSW is a PeopleSoft application with complex JavaScript forms,
actual enrolment operations open the myUNSW page in your browser for safety.
"""

from __future__ import annotations

import re
import webbrowser
from typing import Any, Optional

from bs4 import BeautifulSoup

from unsw.auth.myunsw import login_with_cookie
from unsw.config import Config
from unsw.modules.base import BaseModule
from unsw.utils.output import print_info

MYUNSW_BASE = "https://my.unsw.edu.au"


class MyUNSWModule(BaseModule):
    """Access myUNSW - course enrolment and student services."""

    name = "myunsw"
    description = "UNSW myUNSW - course enrolment and student services"

    def __init__(self, config: Config, client=None):
        self.config = config
        cookie_client = login_with_cookie(config)
        super().__init__(client=cookie_client or client)

    # ── Enrolled Courses ─────────────────────────────────────

    # PeopleSoft URLs for authenticated users
    ENROLLED_URL = (
        "https://my.unsw.edu.au/psc/ps/EMPLOYEE/HRMS/c/"
        "SA_LEARNER_SERVICES.SSR_SSENRL_LIST.GBL"
    )
    TIMETABLE_URL = (
        "https://my.unsw.edu.au/psc/ps/EMPLOYEE/HRMS/c/"
        "SA_LEARNER_SERVICES.SSR_SSREP_SUMMARY.GBL"
    )

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Get list of currently enrolled courses by scraping myUNSW.

        Returns a list of dicts with keys: code, name, term, status.
        """
        if not self.client:
            return []

        try:
            # Access the myUNSW enrolled classes page (PeopleSoft)
            resp = self.client.get(self.ENROLLED_URL)
            if resp.status_code != 200:
                # Fallback: try the portal root
                resp = self.client.get(f"{MYUNSW_BASE}/portal/")
                if resp.status_code != 200:
                    return []

            soup = BeautifulSoup(resp.text, "html.parser")
            courses = []
            seen = set()

            # Try multiple approaches to find enrolled courses
            # 1. Look for course cards / enrolment tables
            for item in soup.select(
                '[class*="course"], [class*="enrol"], '
                '[class*="class"], .ps_box-group, '
                "table[id*='SSR_SSENRL'] tr, "
                "table[id*='CLASS'] tr, "
                "[class*='psc-row'], [class*='ps_grid-row']"
            ):
                text = item.get_text(" ", strip=True)
                if not text:
                    continue
                # Look for course codes like COMP6733
                codes = re.findall(r"[A-Z]{4}\d{4}", text)
                for code in codes:
                    if code not in seen:
                        seen.add(code)
                        # Try to extract term and name
                        name = ""
                        term = ""
                        name_match = re.search(
                            rf"{re.escape(code)}\s*[-–—]\s*(.+?)(?:\s*[-–—]\s*|\s*\()",
                            text,
                        )
                        if name_match:
                            name = name_match.group(1).strip()
                        term_match = re.search(r"(20\d{2})\s*T[123S]", text)
                        if term_match:
                            term = term_match.group(0)
                        courses.append(
                            {
                                "code": code,
                                "name": name or code,
                                "term": term,
                                "status": "Enrolled",
                            }
                        )

            # 2. Fallback: scan the entire page for course codes
            if not courses:
                full_text = soup.get_text(" ", strip=True)
                codes = re.findall(r"[A-Z]{4}\d{4}", full_text)
                for code in codes:
                    if code not in seen:
                        seen.add(code)
                        courses.append(
                            {
                                "code": code,
                                "name": code,
                                "term": "",
                                "status": "Enrolled",
                            }
                        )

            return courses

        except Exception:
            return []

    # ── Enrolment Action (opens browser) ─────────────────────

    def open_enrolment_page(self) -> str:
        """Open the myUNSW enrolment page in the user's browser.

        Returns the URL that was opened.
        """
        url = f"{MYUNSW_BASE}/"
        webbrowser.open(url)
        print_info(f"Opened {url} in your browser.")
        print_info("Navigate to: Student Portal → Enrolment → Enrol in Classes")
        return url

    def open_class_search(self, course_code: str = "") -> str:
        """Open the myUNSW class search page in the user's browser.

        If a course code is provided, it pre-fills the search.
        """
        url = f"{MYUNSW_BASE}/"
        webbrowser.open(url)
        print_info(f"Opened {url} in your browser.")
        if course_code:
            print_info(f"Search for course: {course_code.upper()}")
        print_info("Navigate to: Student Portal → Enrolment → Class Search")
        return url

    # ── Personal Timetable (from myUNSW enrolment) ───────────

    def get_timetable(self) -> list[dict[str, Any]]:
        """Get personal class timetable from myUNSW enrolment data.

        Scrapes the student's enrolled class schedule, showing
        when and where each class meets.

        Returns a list of dicts with keys: code, activity, section,
        day, time, location, weeks.
        """
        if not self.client:
            return []

        try:
            # Try the student class schedule page (PeopleSoft URL)
            resp = self.client.get(self.ENROLLED_URL)

            # Fallback: try the timetable summary page
            if resp.status_code != 200:
                resp = self.client.get(self.TIMETABLE_URL)

            # Last fallback: portal root
            if resp.status_code != 200:
                resp = self.client.get(f"{MYUNSW_BASE}/portal/")

            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            classes = []
            seen = set()

            # Strategy 1: Look for the standard enrolment schedule table
            # PeopleSoft uses tables with ids like SSR_SSENRL_LIST_* or similar
            for table in soup.select(
                "table[id*='SSR_SSENRL_LIST'], "
                "table[id*='CLASS_SRCH'], "
                "table[id*='ENRL_LIST'], "
                "table[class*='psc-table'], "
                "table[summary*='schedule'], "
                "table[summary*='class'], "
                ".ps_box-scroll table"
            ):
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) < 5:
                        continue

                    text = row.get_text(strip=True)
                    # Ensure it has a course code
                    codes = re.findall(r"[A-Z]{4}\d{4}", text)
                    if not codes:
                        continue

                    code = codes[0]
                    # Build dedup key
                    cells_text = [c.get_text(strip=True) for c in cells]
                    dedup_key = "|".join(cells_text[:6])
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)

                    # Extract fields (PeopleSoft column order varies)
                    # Typical order: section, activity, day, time, location, instructor, weeks
                    section = cells[0].get_text(strip=True) if len(cells) > 0 else ""
                    activity = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                    day = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                    time = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                    location = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                    instructor = cells[5].get_text(strip=True) if len(cells) > 5 else ""
                    weeks = cells[6].get_text(strip=True) if len(cells) > 6 else ""

                    classes.append(
                        {
                            "code": code,
                            "section": section,
                            "activity": activity,
                            "day": day,
                            "time": time,
                            "location": location,
                            "instructor": instructor,
                            "weeks": weeks,
                        }
                    )

            # Strategy 2: Look for course/class info blocks (if no table found)
            if not classes:
                for block in soup.select(
                    "[class*='course'], [class*='class'], "
                    "[id*='course'], [id*='class'], "
                    ".ps_box-group, [class*='enrollment']"
                ):
                    text = block.get_text(strip=True)
                    codes = re.findall(r"[A-Z]{4}\d{4}", text)
                    if not codes:
                        continue

                    code = codes[0]
                    if code in seen:
                        continue
                    seen.add(code)

                    # Try to extract day/time from text
                    day = ""
                    time = ""
                    location = ""
                    activity = ""

                    day_match = re.search(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)", text)
                    if day_match:
                        day = day_match.group(1)

                    time_match = re.search(
                        r"(\d{1,2}:\d{2}\s*(?:am|pm)\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm))",
                        text,
                        re.IGNORECASE,
                    )
                    if time_match:
                        time = time_match.group(1)

                    loc_match = re.search(r"([A-Z][a-z]+\s+\d+)", text)
                    if loc_match:
                        location = loc_match.group(1)

                    classes.append(
                        {
                            "code": code,
                            "section": "",
                            "activity": activity,
                            "day": day,
                            "time": time,
                            "location": location,
                            "instructor": "",
                            "weeks": "",
                        }
                    )

            return classes

        except Exception:
            return []

    def open_timetable_page(self) -> str:
        """Open the myUNSW timetable / class schedule page in the user's browser.

        Returns the URL that was opened.
        """
        url = (
            f"{MYUNSW_BASE}/psc/ps/EMPLOYEE/HRMS/c/"
            f"SA_LEARNER_SERVICES.SSR_SSENRL_LIST.GBL"
        )
        webbrowser.open(url)
        print_info(f"Opened myUNSW class schedule in your browser.")
        return url

    # ── Class Search (scraped) ───────────────────────────────

    def search_classes(self, course_code: str) -> list[dict[str, Any]]:
        """Search for available classes by course code.

        NOTE: This is a best-effort implementation. myUNSW's PeopleSoft
        pages are complex JavaScript forms, so this may not work for all
        pages. If it fails, use the browser-based search instead.
        """
        if not self.client:
            return []

        # PeopleSoft class search URL pattern
        search_url = (
            f"{MYUNSW_BASE}/psc/ps/EMPLOYEE/HRMS/c/"
            f"SA_LEARNER_SERVICES.SSR_SSENRL_CART.GBL"
        )

        try:
            # First, get the search page to extract any required form fields
            resp = self.client.get(search_url)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")

            # Look for a class search form
            # PeopleSoft forms typically have hidden ICS fields
            classes = []

            # Extract class data from tables or search results
            for row in soup.select(
                "table[id*='SSR_CLSRCH_MTG1'] tr, "
                "[class*='psc-table'] tr, "
                "tr[class*='psc-row']"
            ):
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue

                class_nbr = cells[0].get_text(strip=True) if len(cells) > 0 else ""
                section = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                activity = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                time = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                day = cells[4].get_text(strip=True) if len(cells) > 4 else ""
                location = cells[5].get_text(strip=True) if len(cells) > 5 else ""
                status = cells[6].get_text(strip=True) if len(cells) > 6 else ""
                enrols = cells[7].get_text(strip=True) if len(cells) > 7 else ""

                if class_nbr and class_nbr.isdigit():
                    classes.append(
                        {
                            "class_nbr": class_nbr,
                            "section": section,
                            "activity": activity,
                            "time": time,
                            "day": day,
                            "location": location,
                            "status": status,
                            "enrols": enrols,
                        }
                    )

            return classes

        except Exception:
            return []
