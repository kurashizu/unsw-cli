"""Moodle module - eLearning content from moodle.telt.unsw.edu.au.

Requires MoodleSession cookie (from browser after Azure AD SSO login).
REST API is not available on UNSW Moodle, so we scrape pages using the cookie.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from bs4 import BeautifulSoup

from unsw.auth.moodle import login_with_cookie
from unsw.config import Config
from unsw.modules.base import BaseModule

MOODLE_BASE = "https://moodle.telt.unsw.edu.au"


class MoodleModule(BaseModule):
    """Access UNSW Moodle - courses, assignments, grades."""

    name = "moodle"
    description = "UNSW Moodle - eLearning platform"

    def __init__(self, config: Config, client=None):
        self.config = config
        cookie_client = login_with_cookie(config)
        self.client = cookie_client or client

    # ── Courses ──────────────────────────────────────────────

    def get_courses(self) -> list[dict[str, Any]]:
        """Get list of enrolled courses by scraping the dashboard."""
        if not self.client:
            return []

        try:
            resp = self.client.get(f"{MOODLE_BASE}/my/")
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            courses = []
            seen_ids = set()

            # Try multiple selectors for course cards/links
            course_links = soup.select(
                'a[href*="/course/view.php"], '
                ".course_title a, "
                '[class*="coursename"] a, '
                '.card-body a[href*="course"], '
                '[data-region="course-content"] a[href*="course"], '
                ".course-summary a"
            )

            for a in course_links:
                href = a.get("href", "")
                name = a.get_text(strip=True)
                if not name or not href:
                    continue

                # Normalise href
                if href.startswith("//"):
                    href = f"https:{href}"
                elif href.startswith("/"):
                    href = f"{MOODLE_BASE}{href}"

                # Extract course ID from URL
                match = re.search(r"id=(\d+)", href)
                cid = match.group(1) if match else ""

                # Extract shortname from URL or text
                shortname = ""
                sn_match = re.search(r"/course/(?:view\.php\?id=\d+|([^/]+))", href)
                if sn_match and sn_match.group(1):
                    shortname = sn_match.group(1)

                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    courses.append(
                        {
                            "id": cid,
                            "shortname": shortname,
                            "fullname": name,
                            "url": href,
                        }
                    )

            return courses

        except Exception:
            return []

    # ── Assignments ──────────────────────────────────────────

    def get_assignments(self) -> list[dict[str, Any]]:
        """Get upcoming assignments by scraping the dashboard timeline."""
        if not self.client:
            return []

        assignments = []

        # Try the dashboard timeline first
        try:
            resp = self.client.get(f"{MOODLE_BASE}/my/")
            if resp.status_code == 200:
                dashboard = self._scrape_dashboard_assignments(resp.text)
                assignments.extend(dashboard)
        except Exception:
            pass

        # Also try the calendar upcoming view
        try:
            resp = self.client.get(
                f"{MOODLE_BASE}/calendar/view.php",
                params={"view": "upcoming", "time": "0"},
            )
            if resp.status_code == 200:
                calendar = self._scrape_calendar_assignments(resp.text)
                # Merge, avoiding duplicates by name
                existing_names = {a["name"] for a in assignments}
                for item in calendar:
                    if item["name"] not in existing_names:
                        assignments.append(item)
                        existing_names.add(item["name"])
        except Exception:
            pass

        return assignments

    def _scrape_dashboard_assignments(self, html: str) -> list[dict[str, Any]]:
        """Scrape assignments from the Moodle dashboard timeline."""
        soup = BeautifulSoup(html, "html.parser")
        assignments = []

        # Moodle 4.x timeline events
        for item in soup.select('[data-region="event-list-item"], .timeline-event'):
            # Course name
            course_el = item.select_one(
                '[data-region="event-list-course"], .event-course, .coursename'
            )
            course = course_el.get_text(strip=True) if course_el else ""

            # Activity name
            name_el = item.select_one(
                '[data-region="event-list-name"], a[href*="assign"], .event-name a'
            )
            name = name_el.get_text(strip=True) if name_el else ""

            # Due date
            date_el = item.select_one(
                '[data-region="event-list-date"], .date, time, [class*="date"]'
            )
            due = ""
            if date_el:
                due = date_el.get_text(strip=True)
                if date_el.name == "time" and date_el.get("datetime"):
                    due = date_el.get("datetime", "")

            # Link
            link = ""
            if name_el and name_el.name == "a" and name_el.get("href"):
                link = name_el["href"]
            elif name_el:
                parent_a = name_el.find_parent("a")
                if parent_a and parent_a.get("href"):
                    link = parent_a["href"]

            if name:
                assignments.append(
                    {
                        "course": course,
                        "name": name,
                        "due": due,
                        "url": link
                        if not link.startswith("/")
                        else f"{MOODLE_BASE}{link}",
                    }
                )

        # Also try Moodle 3.x assignment tables
        for row in soup.select("table.generaltable tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                name_cell = cells[0]
                name = name_cell.get_text(strip=True)
                due_cell = cells[1] if len(cells) > 1 else None
                due = due_cell.get_text(strip=True) if due_cell else ""

                link = ""
                a_tag = name_cell.find("a")
                if a_tag and a_tag.get("href"):
                    link = a_tag["href"]
                    if link.startswith("/"):
                        link = f"{MOODLE_BASE}{link}"

                if name:
                    assignments.append(
                        {
                            "course": "",
                            "name": name,
                            "due": due,
                            "url": link,
                        }
                    )

        return assignments

    def _scrape_calendar_assignments(self, html: str) -> list[dict[str, Any]]:
        """Scrape upcoming assignments from the calendar view."""
        soup = BeautifulSoup(html, "html.parser")
        assignments = []

        for event in soup.select(".event, [data-eventtype-expected] li, .card"):
            # Skip if not an assignment-like event
            event_text = event.get_text(strip=True).lower()
            if not any(
                kw in event_text for kw in ["due", "assign", "submission", "deadline"]
            ):
                continue

            name_el = event.select_one("a, .eventname, .card-title")
            name = name_el.get_text(strip=True) if name_el else ""

            date_el = event.select_one("time, .date, .col-11")
            due = date_el.get_text(strip=True) if date_el else ""
            if date_el and date_el.name == "time" and date_el.get("datetime"):
                due = date_el.get("datetime", "")

            link = ""
            if name_el and name_el.name == "a" and name_el.get("href"):
                link = name_el["href"]
                if link.startswith("/"):
                    link = f"{MOODLE_BASE}{link}"

            if name:
                assignments.append(
                    {
                        "course": "",
                        "name": name,
                        "due": due,
                        "url": link,
                    }
                )

        return assignments

    # ── Grades ───────────────────────────────────────────────

    def get_grades(self) -> list[dict[str, Any]]:
        """Get grades by scraping each course's grade page."""
        if not self.client:
            return []

        courses = self.get_courses()
        all_grades = []

        for course in courses[:10]:  # Limit to 10 courses
            course_id = course.get("id")
            if not course_id:
                continue

            try:
                resp = self.client.get(
                    f"{MOODLE_BASE}/grade/report/user/index.php",
                    params={"id": course_id},
                )
                if resp.status_code != 200:
                    continue

                grades = self._scrape_grade_table(resp.text, course)
                all_grades.extend(grades)
            except Exception:
                continue

        return all_grades

    def _scrape_grade_table(
        self, html: str, course: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Scrape grades from a course's grade report page."""
        soup = BeautifulSoup(html, "html.parser")
        grades = []

        # Look for the grade table
        table = soup.select_one(
            "table.generaltable, table.user-grade, [class*='gradetable'], #user-grade"
        )
        if not table:
            return grades

        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue

            # Get item name (first cell)
            item_name = cells[0].get_text(strip=True)
            if not item_name or item_name.lower() in (
                "grade item",
                "course total",
                "total",
            ):
                continue

            # Get grade (usually second-to-last or third-to-last cell)
            grade_text = ""
            for cell in reversed(cells):
                text = cell.get_text(strip=True)
                if text and text != "-" and not text.startswith("("):
                    grade_text = text
                    break

            if grade_text:
                grades.append(
                    {
                        "course": course.get("fullname", course.get("shortname", "")),
                        "item": item_name,
                        "grade": grade_text,
                        "course_id": course.get("id", ""),
                    }
                )

        return grades

    # ── Calendar / Events ────────────────────────────────────

    def get_upcoming_events(self) -> list[dict[str, Any]]:
        """Get upcoming events from the calendar."""
        if not self.client:
            return []

        try:
            resp = self.client.get(
                f"{MOODLE_BASE}/calendar/view.php",
                params={"view": "upcoming"},
            )
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            events = []

            for event in soup.select(
                '[data-region="event-list-item"], '
                ".calendar_event, "
                ".event_card, "
                "li.event"
            ):
                name_el = event.select_one(
                    '[data-region="event-list-name"], '
                    ".event-name a, "
                    "a[href*='calendar']"
                )
                name = name_el.get_text(strip=True) if name_el else ""

                date_el = event.select_one(
                    '[data-region="event-list-date"], .date, time'
                )
                date = date_el.get_text(strip=True) if date_el else ""

                link = ""
                if name_el and name_el.name == "a" and name_el.get("href"):
                    link = name_el["href"]
                    if link.startswith("/"):
                        link = f"{MOODLE_BASE}{link}"

                if name:
                    events.append(
                        {
                            "name": name,
                            "date": date,
                            "url": link,
                        }
                    )

            return events

        except Exception:
            return []
