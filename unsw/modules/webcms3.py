"""WebCMS3 module - CSE course content from webcms3.cse.unsw.edu.au.

Requires zID + zPass authentication.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from unsw.auth.webcms3 import login as webcms3_login
from unsw.config import Config
from unsw.modules.base import BaseModule

WEBCMS3_BASE = "https://webcms3.cse.unsw.edu.au"


class WebCMS3Module(BaseModule):
    """Access CSE course content from WebCMS3."""

    name = "webcms3"
    description = "UNSW CSE WebCMS3 - course content and announcements"

    def __init__(self, config: Config, client=None):
        self.config = config
        # Try to authenticate
        authenticated_client = webcms3_login(config)
        super().__init__(client=authenticated_client or client)

    def get_courses(self) -> list[dict[str, Any]]:
        """Get the list of courses for the logged-in user.

        The user's enrolled courses are shown in the navigation bar.
        """
        if not self.client:
            return []

        try:
            resp = self.client.get(f"{WEBCMS3_BASE}/")
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            courses = []
            seen = set()

            # Course URL pattern: /COURSECODE/TERM/  e.g. /COMP6733/26T2/
            course_pattern = re.compile(r"/([A-Z]{4}\d{4})/(\d{2}T[123S])/?$")

            # Only look at nav bar links for enrolled courses
            nav = soup.find("nav")
            if nav:
                for a in nav.find_all("a", href=True):
                    href = a.get("href", "")
                    match = course_pattern.search(href)
                    if match:
                        code = match.group(1)
                        term = match.group(2)
                        name = a.get_text(strip=True) or code
                        if code not in seen:
                            seen.add(code)
                            courses.append(
                                {
                                    "code": code,
                                    "name": name,
                                    "term": term,
                                    "url": f"{WEBCMS3_BASE}/{code}/{term}/",
                                }
                            )

            return courses

        except Exception:
            return []

    def get_course_content(self, course_code: str) -> list[dict[str, Any]]:
        """Get content items for a specific course."""
        if not self.client:
            return []

        # We need the term. Try to find it from courses list.
        courses = self.get_courses()
        term = ""
        for c in courses:
            if c["code"].upper() == course_code.upper():
                term = c.get("term", "")
                break

        if not term:
            # Try common terms as fallback
            return []

        url = f"{WEBCMS3_BASE}/{course_code.upper()}/{term}/"
        try:
            resp = self.client.get(url)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            content = []

            # Extract resource and activity links
            for a in soup.select(
                "a[href*='/resources/'], a[href*='/activities/'], "
                "a[href*='/forums/'], a[href*='/timetable'], "
                "a[href*='/outline'], a[href*='/groups/']"
            ):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if text and href:
                    if href.startswith("/"):
                        href = f"{WEBCMS3_BASE}{href}"
                    content.append(
                        {
                            "title": text,
                            "url": href,
                        }
                    )

            # Also get sidebar navigation items
            nav_links = soup.select(
                "nav a, [class*='sidebar'] a, [class*='nav'] a, [class*='menu'] a"
            )
            seen_urls = {c["url"] for c in content}
            for a in nav_links:
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if text and href and course_code.upper() in href.upper():
                    full_url = f"{WEBCMS3_BASE}{href}" if href.startswith("/") else href
                    if full_url not in seen_urls and "outline" not in href.lower():
                        seen_urls.add(full_url)
                        content.append(
                            {
                                "title": text,
                                "url": full_url,
                            }
                        )

            return content

        except Exception:
            return []

    def get_announcements(self) -> list[dict[str, Any]]:
        """Get recent announcements from the dashboard."""
        if not self.client:
            return []

        try:
            resp = self.client.get(f"{WEBCMS3_BASE}/")
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            announcements = []

            # WebCMS3 dashboard has notices/announcements as h4 items
            for item in soup.select(".notices h4, [class*='notice'] h4, .announcement"):
                title = item.get_text(strip=True)
                # Get the parent for more context
                parent = item.find_parent()
                body = parent.get_text(strip=True) if parent else title
                # Extract course code from text like "Posted by ... on COMP6733 ..."
                course = ""
                course_match = re.search(r"on([A-Z]{4}\d{4})", body)
                if course_match:
                    course = course_match.group(1)
                announcements.append(
                    {
                        "title": title,
                        "course": course,
                        "body": body[:300] + "..." if len(body) > 300 else body,
                    }
                )

            return announcements

        except Exception:
            return []
