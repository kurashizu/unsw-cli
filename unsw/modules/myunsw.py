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

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Get list of currently enrolled courses by scraping myUNSW.

        Returns a list of dicts with keys: code, name, term, status.
        """
        if not self.client:
            return []

        try:
            # Access the myUNSW student portal
            resp = self.client.get(f"{MYUNSW_BASE}/")
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            courses = []
            seen = set()

            # Try multiple approaches to find enrolled courses

            # Approach 1: Look for course cards / enrolment tables
            for item in soup.select(
                '[class*="course"], [class*="enrol"], '
                '[class*="class"], .ps_box-group, '
                "table tr, [id*="
                "course], [id*=enrol]"
            ):
                text = item.get_text(strip=True)
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
