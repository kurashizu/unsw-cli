"""myUNSW module - course enrolment and student services.

myUNSW is now a JavaScript SPA behind Azure AD SSO. Cookies alone
don't authenticate cross-domain — the DISSESSIONAuthnDelegation JWT
appears to be tied to the browser session. So we drive a real Playwright
browser, load the saved cookies, navigate to the portal, and scrape
the post-JS rendered DOM.

For operations that can't be reliably scraped (like enrolment), we
fall back to opening the user's browser with step-by-step instructions.
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
from unsw.utils.output import print_info, print_warning

MYUNSW_BASE = "https://my.unsw.edu.au"

# URLs that may contain enrolled-class data (we try them in order)
PORTAL_URLS_TO_TRY = [
    f"{MYUNSW_BASE}/portal/",
    f"{MYUNSW_BASE}/portal/student/",
    f"{MYUNSW_BASE}/portal/enrolment/",
]


def _load_myunsw_cookies(config: Config) -> list[dict[str, str]]:
    """Load saved myUNSW cookies as Playwright-compatible cookie dicts."""
    saved = config.load_cookies()
    cookies = []
    for key, value in saved.items():
        if not key.startswith("myunsw_"):
            continue
        cookies.append(
            {
                "name": key.removeprefix("myunsw_"),
                "value": value,
                "domain": ".my.unsw.edu.au",
                "path": "/",
            }
        )
    return cookies


async def _scrape_with_playwright(
    config: Config, urls: list[str]
) -> tuple[Optional[str], Optional[str]]:
    """Open a headless browser with saved browser state, navigate to URLs,
    return the final URL and the rendered HTML of the last successful page.

    Uses Playwright's storage_state to load the full browser context
    (cookies + localStorage + sessionStorage + IndexedDB). This is
    critical for myUNSW because its DISSESSIONAuthnDelegation JWT appears
    to be session-bound and doesn't work cross-session via plain cookies.

    If authentication fails (we land back on a login page), returns None.
    """
    from playwright.async_api import async_playwright

    state_path = CONFIG_DIR / "myunsw_storage.json"
    storage_state = None
    if state_path.exists():
        try:
            with open(state_path) as f:
                storage_state = json.load(f)
        except Exception:
            pass

    # Fall back to cookies if no storage state
    cookies = _load_myunsw_cookies(config)
    if not storage_state and not cookies:
        return None, None

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception:
            return None, None

        try:
            if storage_state:
                context = await browser.new_context(storage_state=storage_state)
            else:
                context = await browser.new_context()
                await context.add_cookies(cookies)
            page = await context.new_page()

            final_url = None
            final_html = None

            for url in urls:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    # Give JS time to render
                    await asyncio.sleep(2)
                    final_url = page.url
                    # If we got bounced back to a login page, give up
                    if (
                        "sso.unsw.edu.au" in final_url.lower()
                        or "login.microsoftonline" in final_url.lower()
                    ):
                        return None, None
                    # Check if we're on the public search page (also unauthed)
                    html = await page.content()
                    if "Single Sign On" in html or "Welcome to Single Sign On" in html:
                        return None, None
                    final_url = final_url
                    final_html = html
                    # If we found something useful, stop
                    break
                except Exception:
                    continue

            await context.close()
            await browser.close()
            return final_url, final_html

        except Exception:
            try:
                await browser.close()
            except Exception:
                pass
            return None, None


def _scrape_courses_sync(config: Config) -> list[dict[str, Any]]:
    """Synchronous wrapper around _scrape_with_playwright for course scraping."""
    try:
        url, html = asyncio.run(_scrape_with_playwright(config, PORTAL_URLS_TO_TRY))
    except Exception:
        return []

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    courses = []
    seen = set()

    # Strategy 1: Look for course codes anywhere in the rendered page
    full_text = soup.get_text(" ", strip=True)
    codes = re.findall(r"[A-Z]{4}\d{4}", full_text)
    for code in codes:
        if code not in seen:
            seen.add(code)
            # Try to extract course name and term from surrounding text
            name = ""
            term = ""
            pattern = rf"{re.escape(code)}\s*[-–—:]?\s*([A-Z][A-Za-z][^\(\)]{{3,60}}?)(?:\s*[-–—]\s*(20\d{{2}}\s*T[123S])|\s*\()"
            m = re.search(pattern, full_text)
            if m:
                name = m.group(1).strip()
                if m.group(2):
                    term = m.group(2)
            courses.append(
                {
                    "code": code,
                    "name": name or code,
                    "term": term,
                    "status": "Enrolled",
                }
            )

    return courses


def _scrape_timetable_sync(config: Config) -> list[dict[str, Any]]:
    """Synchronous wrapper around _scrape_with_playwright for timetable scraping."""
    try:
        url, html = asyncio.run(_scrape_with_playwright(config, PORTAL_URLS_TO_TRY))
    except Exception:
        return []

    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    classes = []
    seen = set()

    full_text = soup.get_text(" ", strip=True)
    codes = re.findall(r"[A-Z]{4}\d{4}", full_text)

    for code in codes:
        if code in seen:
            continue
        seen.add(code)

        # Look for day/time/location patterns near this code
        # Match patterns like "Mon 13:00-15:00" or "Monday 1:00 PM"
        day_match = re.search(
            rf"{re.escape(code)}.{{0,200}}?((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*)",
            full_text,
        )
        time_match = re.search(
            rf"{re.escape(code)}.{{0,300}}?"
            r"(\d{1,2}:\d{2}\s*(?:am|pm)?\s*[-–—]\s*\d{1,2}:\d{2}\s*(?:am|pm)?)",
            full_text,
            re.IGNORECASE,
        )
        loc_match = re.search(
            rf"{re.escape(code)}.{{0,400}}?((?:UNSW|Ainsworth|Bus|Room|Lecture)[^\s,]*)",
            full_text,
        )

        classes.append(
            {
                "code": code,
                "section": "",
                "activity": "",
                "day": day_match.group(1) if day_match else "",
                "time": time_match.group(1) if time_match else "",
                "location": loc_match.group(1) if loc_match else "",
                "weeks": "",
            }
        )

    return classes


class MyUNSWModule(BaseModule):
    """Access myUNSW - course enrolment and student services."""

    name = "myunsw"
    description = "UNSW myUNSW - course enrolment and student services"

    def __init__(self, config: Config, client=None):
        self.config = config
        cookie_client = login_with_cookie(config)
        super().__init__(client=cookie_client or client)

    # ── Enrolled Courses ─────────────────────────────────────

    ENROLLED_URL = (
        "https://my.unsw.edu.au/psc/ps/EMPLOYEE/HRMS/c/"
        "SA_LEARNER_SERVICES.SSR_SSENRL_LIST.GBL"
    )
    TIMETABLE_URL = (
        "https://my.unsw.edu.au/psc/ps/EMPLOYEE/HRMS/c/"
        "SA_LEARNER_SERVICES.SSR_SSREP_SUMMARY.GBL"
    )

    def get_enrolled_courses(self) -> list[dict[str, Any]]:
        """Get list of currently enrolled courses.

        Uses Playwright to drive a headless browser with saved cookies,
        navigates to the myUNSW portal, waits for JS to render, then
        scrapes the DOM for course codes.
        """
        if not self.client:
            print_info(
                "myUNSW not logged in. Run: unsw login --platform myunsw --browser"
            )
            return []

        state_path = CONFIG_DIR / "myunsw_storage.json"
        if not state_path.exists():
            print_info(
                "myUNSW session needs to be captured. "
                "Run: unsw login --platform myunsw --browser"
            )

        return _scrape_courses_sync(self.config)

    # ── Enrolment Action (opens browser) ─────────────────────

    def open_enrolment_page(self) -> str:
        """Open the myUNSW enrolment page in the user's browser."""
        url = f"{MYUNSW_BASE}/"
        webbrowser.open(url)
        print_info(f"Opened {url} in your browser.")
        print_info("Navigate to: Student Portal → Enrolment → Enrol in Classes")
        return url

    def open_class_search(self, course_code: str = "") -> str:
        """Open the myUNSW class search page in the user's browser."""
        url = f"{MYUNSW_BASE}/"
        webbrowser.open(url)
        print_info(f"Opened {url} in your browser.")
        if course_code:
            print_info(f"Search for course: {course_code.upper()}")
        print_info("Navigate to: Student Portal → Enrolment → Class Search")
        return url

    # ── Personal Timetable ────────────────────────────────────

    def get_timetable(self) -> list[dict[str, Any]]:
        """Get personal class timetable from myUNSW enrolment data.

        Uses Playwright to render the SPA and extract day/time/location
        for each enrolled course.
        """
        if not self.client:
            print_info(
                "myUNSW not logged in. Run: unsw login --platform myunsw --browser"
            )
            return []

        state_path = CONFIG_DIR / "myunsw_storage.json"
        if not state_path.exists():
            print_info(
                "myUNSW session needs to be captured. "
                "Run: unsw login --platform myunsw --browser"
            )

        return _scrape_timetable_sync(self.config)

    def open_timetable_page(self) -> str:
        """Open the myUNSW class schedule page in the user's browser."""
        url = f"{MYUNSW_BASE}/portal/"
        webbrowser.open(url)
        print_info(f"Opened myUNSW class schedule in your browser.")
        return url

    # ── Class Search (scraped) ───────────────────────────────

    def search_classes(self, course_code: str) -> list[dict[str, Any]]:
        """Search for available classes by course code.

        NOTE: myUNSW's class search is a complex JavaScript form. This is
        a best-effort fallback — for full functionality, use the browser.
        """
        if not self.client:
            return []

        try:
            resp = self.client.get(self.ENROLLED_URL)
            if resp.status_code != 200:
                resp = self.client.get(f"{MYUNSW_BASE}/portal/")
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            classes = []
            for row in soup.select(
                "table[id*='SSR_SSENRL_LIST'] tr, "
                "table[id*='CLASS_SRCH'] tr, "
                "table[class*='psc-table'] tr"
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
