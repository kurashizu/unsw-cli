"""Timetable module - class schedule from timetable.unsw.edu.au.

UNSW Timetable website provides public HTML pages with class/offering data.
No authentication required.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from unsw.modules.base import BaseModule

TIMETABLE_BASE = "https://timetable.unsw.edu.au"


class TimetableModule(BaseModule):
    """Access class timetables from timetable.unsw.edu.au."""

    name = "timetable"
    description = "UNSW Timetable - class schedules and offerings"

    def get_course_classes(self, code: str, year: int = 2026) -> list[dict[str, Any]]:
        """Get class/timetable information for a course.

        Parses the timetable detail page for a course.
        """
        url = f"{TIMETABLE_BASE}/{year}/{code.upper()}.html"
        try:
            resp = self.client.get(url)
            if resp.status_code != 200:
                return []

            return self._parse_class_details(resp.text, code)
        except Exception:
            return []

    def search_by_year(self, year: int = 2026) -> list[dict[str, str]]:
        """Get all subject areas available for a given year."""
        url = f"{TIMETABLE_BASE}/{year}/subjectSearch.html"
        results = []

        try:
            resp = self.client.get(url)
            if resp.status_code != 200:
                return results

            soup = BeautifulSoup(resp.text, "html.parser")
            # Extract subject area links
            for a in soup.find_all("a", href=True):
                href = a["href"]
                match = re.match(r"^([A-Z]+)(KENS|COFA|CANC|ADFA|BENG)\.html$", href)
                if match:
                    area_code = match.group(1)
                    campus = match.group(2)
                    results.append(
                        {
                            "code": area_code,
                            "campus": campus,
                            "url": f"{TIMETABLE_BASE}/{year}/{href}",
                        }
                    )

            # Deduplicate by code
            seen = set()
            unique = []
            for r in results:
                if r["code"] not in seen:
                    seen.add(r["code"])
                    unique.append(r)
            return unique

        except Exception:
            return []

    def get_subject_area_courses(
        self, area_code: str, year: int = 2026
    ) -> list[dict[str, str]]:
        """Get all courses in a subject area (e.g., 'COMP')."""
        url = f"{TIMETABLE_BASE}/{year}/{area_code.upper()}KENS.html"
        results = []

        try:
            resp = self.client.get(url)
            if resp.status_code != 200:
                return results

            codes = re.findall(rf'href="({area_code.upper()}\d{{4}})\.html"', resp.text)
            return [{"code": c} for c in sorted(set(codes))]
        except Exception:
            return []

    def _parse_class_details(self, html: str, code: str) -> list[dict[str, Any]]:
        """Parse class details from the timetable HTML page.

        The timetable pages use old-school HTML tables.
        Structure: header rows with "Teaching Period X", then column headers,
        then data rows with [Activity, Period, Class#, Section, Status, Enrols, Schedule].
        We iterate row-by-row and extract period from header rows.
        """
        soup = BeautifulSoup(html, "html.parser")
        classes = []
        current_period = ""

        # Find the main data table (usually the largest one)
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all("td")
                text_cells = [c.get_text(strip=True) for c in cells]

                # Detect single-cell period headers like "Teaching Period One", "Summer Teaching Period"
                if len(cells) == 1:
                    text = text_cells[0]
                    if (
                        "teaching period" in text.lower()
                        or "summer teaching" in text.lower()
                    ):
                        # Normalize: "Teaching Period One" -> "T1", "Summer Teaching Period" -> "Summer"
                        current_period = self._normalize_period(text)
                    continue

                # Skip header rows (Activity | Period | Class | Section | Status | ...)
                if len(cells) >= 7:
                    first_cell = text_cells[0].strip().lower()
                    if first_cell in ("activity", "section", "class", "cmp"):
                        continue

                    # Check if this is a summary/detail row (has a link or special formatting)
                    class_info = self._parse_class_row(text_cells[:7])
                    if class_info:
                        class_info["course"] = code.upper()
                        class_info["period"] = current_period
                        # Deduplicate: same class# + section + activity = same offering
                        key = (
                            class_info["class"],
                            class_info["section"],
                            class_info["activity"],
                            class_info["period"],
                        )
                        if not any(
                            c["class"] == class_info["class"]
                            and c["section"] == class_info["section"]
                            and c["activity"] == class_info["activity"]
                            and c["period"] == class_info["period"]
                            for c in classes
                        ):
                            classes.append(class_info)

        return classes

    @staticmethod
    def _normalize_period(text: str) -> str:
        """Normalize teaching period text to short codes."""
        mapping = {
            "summer teaching period": "Summer",
            "teaching period one": "T1",
            "teaching period two": "T2",
            "teaching period three": "T3",
        }
        lower = text.lower().strip()
        for key, val in mapping.items():
            if key in lower:
                return val
        return text

    def _parse_class_row(self, cells: list[str]) -> dict[str, Any] | None:
        """Parse a single row of class data from 7-cell format.

        Expected format:
        [0] Activity: 'Lecture', 'Tutorial-Laboratory', 'Course Enrolment', etc.
        [1] Period: 'T1', 'T2', 'T3'
        [2] Class#: numeric ID
        [3] Section: '1UGA', 'F09A', 'CR01'
        [4] Status: 'Open', 'Full', 'Limited'
        [5] Enrols/Capacity: '413/432'
        [6] Day/Time/Weeks: 'Tue 09:00 - 11:00 (Weeks:1-5,7-10), Wed ...'
        """
        activity = cells[0].strip()
        section = cells[3].strip() if len(cells) > 3 else ""
        status = cells[4].strip() if len(cells) > 4 else ""

        # Skip header/instruction rows
        if not activity or not section:
            return None
        if activity.lower() in ("activity", "section", "class", "cmp"):
            return None
        if status and status.lower() in ("status",):
            return None

        # Must have a valid status to be a class row
        valid_statuses = {"open", "full", "limited", "cancelled"}
        if status and status.lower() not in valid_statuses:
            # Check if there's also an enrols/capacity pattern
            enrols = cells[5].strip() if len(cells) > 5 else ""
            if not re.match(r"^\d+/\d+$", enrols):
                return None

        # Parse the day/time/weeks from cell 6
        schedule = cells[6].strip() if len(cells) > 6 else ""

        return {
            "activity": activity,
            "period": cells[1].strip() if len(cells) > 1 else "",
            "class": cells[2].strip() if len(cells) > 2 else "",
            "section": section,
            "status": status,
            "enrols": cells[5].strip() if len(cells) > 5 else "",
            "schedule": schedule,
        }
