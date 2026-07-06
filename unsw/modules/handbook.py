"""Handbook module - course and program information from handbook.unsw.edu.au.

The UNSW Handbook is a Next.js app that embeds course data server-side rendered (SSR).
We parse the __NEXT_DATA__ JSON from individual course pages.

For search, we use the timetable subject listing pages to discover course codes,
then scrape individual course pages for details.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from bs4 import BeautifulSoup

from unsw.modules.base import BaseModule
from unsw.utils.output import print_info, print_warning

HANDBOOK_BASE = "https://www.handbook.unsw.edu.au"
TIMETABLE_BASE = "https://timetable.unsw.edu.au"

# Subject area codes -> campus mappings
CAMPUS_SUFFIXES = {
    "KENS": "Kensington",
    "COFA": "Paddington",
    "ATAX": "ATAX",
    "CANC": "Canberra",
    "ADFA": "ADFA",
    "BENG": "Bengaluru",
}


class HandbookModule(BaseModule):
    """Access course and program information from the UNSW Handbook."""

    name = "handbook"
    description = "UNSW Handbook - course and program information"

    def get_course(self, code: str, year: int = 2026) -> dict[str, Any] | None:
        """Get detailed information about a course by its code.

        Scrapes the course page's SSR data (__NEXT_DATA__).
        Tries both undergraduate and postgraduate paths.
        """
        # Try undergrad first, then postgrad
        paths = [
            f"/undergraduate/courses/{year}/{code}/",
            f"/postgraduate/courses/{year}/{code}/",
        ]

        for path in paths:
            url = f"{HANDBOOK_BASE}{path}"
            try:
                resp = self.client.get(url)
                if resp.status_code != 200:
                    continue

                data = self._extract_next_data(resp.text)
                if not data:
                    continue

                page_content = (
                    data.get("props", {}).get("pageProps", {}).get("pageContent", {})
                )
                # Check if we got a real course (not empty)
                if page_content.get("cl_code") == code and page_content.get("title"):
                    return self._format_course(page_content, path)

            except Exception:
                continue

        return None

    def search(
        self, query: str, year: int = 2026, max_results: int = 20
    ) -> list[dict[str, Any]]:
        """Search for courses matching a keyword query.

        Uses the timetable subject listing to discover courses,
        then filters by keyword matching.
        """
        query_lower = query.lower()
        results = []

        # Step 1: Get all course codes from timetable
        all_codes = self._get_all_course_codes(year)

        if not all_codes:
            print_warning("Could not fetch course listing from timetable.")
            return []

        # Step 2: Filter by query (exact or partial match on code)
        matching_codes = [code for code in all_codes if query_lower in code.lower()]

        # Also add fuzzy match: if query is a single word, also search titles
        if len(matching_codes) < 3 and len(query_lower) > 2:
            # Fetch a few courses to check titles
            for code in all_codes[:50]:
                if code.lower().startswith(query_lower[0]):
                    course = self.get_course(code, year)
                    if course and (
                        query_lower in course["title"].lower()
                        or query_lower in course["code"].lower()
                    ):
                        results.append(course)
                        if len(results) >= max_results:
                            break

        # Step 3: Fetch details for matching codes
        for code in matching_codes[:max_results]:
            course = self.get_course(code, year)
            if course:
                results.append(course)
            time.sleep(0.1)  # Be nice to the server

        return results[:max_results]

    def get_program(self, code: str, year: int = 2026) -> dict[str, Any] | None:
        """Get information about a program by its code."""
        # Programs use a different URL pattern
        paths = [
            f"/undergraduate/programs/{year}/{code}/",
            f"/postgraduate/programs/{year}/{code}/",
        ]

        for path in paths:
            url = f"{HANDBOOK_BASE}{path}"
            try:
                resp = self.client.get(url)
                if resp.status_code != 200:
                    continue

                data = self._extract_next_data(resp.text)
                if not data:
                    continue

                page_content = (
                    data.get("props", {}).get("pageProps", {}).get("pageContent", {})
                )
                if page_content.get("title") and page_content.get("cl_code"):
                    return self._format_program(page_content, path)

            except Exception:
                continue

        return None

    def _extract_next_data(self, html: str) -> dict | None:
        """Extract __NEXT_DATA__ JSON from a Next.js SSR page."""
        pattern = re.compile(
            r'<script id="__NEXT_DATA__"[^>]*type="application/json"[^>]*>'
            r"(.*?)</script>",
            re.DOTALL,
        )
        match = pattern.search(html)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return None

    def _format_course(self, data: dict[str, Any], path: str) -> dict[str, Any]:
        """Format course data into a clean dict."""
        study_level = ", ".join(s.get("label", "") for s in data.get("study_level", []))
        academic_org = ""
        if isinstance(data.get("academic_org"), dict):
            academic_org = data["academic_org"].get("value", "")

        parent_org = ""
        if isinstance(data.get("parent_academic_org"), dict):
            parent_org = data["parent_academic_org"].get("value", "")

        status = ""
        if isinstance(data.get("status"), dict):
            status = data["status"].get("label", "")

        return {
            "code": data.get("cl_code", ""),
            "title": data.get("title", ""),
            "credit_points": data.get("credit_points", ""),
            "level": study_level,
            "school": academic_org,
            "faculty": parent_org,
            "status": status,
            "year": data.get("implementation_year", ""),
            "pre_requisites": data.get("pre_requisites", ""),
            "url": f"{HANDBOOK_BASE}{path}",
        }

    def _format_program(self, data: dict[str, Any], path: str) -> dict[str, Any]:
        """Format program data into a clean dict."""
        return {
            "code": data.get("cl_code", ""),
            "title": data.get("title", ""),
            "url": f"{HANDBOOK_BASE}{path}",
            # Programs may have additional fields
        }

    def _get_all_course_codes(self, year: int = 2026) -> list[str]:
        """Get all course codes from timetable subject listing pages."""
        all_codes = set()

        for suffix in CAMPUS_SUFFIXES:
            url = f"{TIMETABLE_BASE}/{year}/subjectSearch.html"
            try:
                resp = self.client.get(url)
                if resp.status_code != 200:
                    continue

                # Extract all links pointing to subject area pages
                soup = BeautifulSoup(resp.text, "html.parser")
                links = []
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if (
                        href.endswith(f"{suffix}.html")
                        and "/" not in href
                        and not href.startswith("http")
                    ):
                        links.append(href)

                # Fetch each subject area page and extract course codes
                for link in links:
                    try:
                        subj_resp = self.client.get(f"{TIMETABLE_BASE}/{year}/{link}")
                        if subj_resp.status_code != 200:
                            continue

                        codes = re.findall(
                            r'href="([A-Z]{4}\d{4})\.html"', subj_resp.text
                        )
                        all_codes.update(codes)
                    except Exception:
                        continue

            except Exception:
                continue

        return sorted(all_codes)

    def search_by_area(self, area_code: str, year: int = 2026) -> list[str]:
        """Get all course codes for a subject area (e.g. 'COMP', 'MATH')."""
        area_upper = area_code.upper()
        all_codes = []
        url = f"{TIMETABLE_BASE}/{year}/{area_upper}KENS.html"
        try:
            resp = self.client.get(url)
            if resp.status_code == 200:
                codes = re.findall(rf'href="({area_upper}\d{{4}})\.html"', resp.text)
                all_codes = sorted(set(codes))
        except Exception:
            pass
        return all_codes
