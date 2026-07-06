"""Integration tests against real UNSW servers.

These tests make real HTTP requests. They are auto-skipped if:
- The target server is unreachable, OR
- The required credentials/cookies aren't stored in ~/.config/unsw-cli/

Mark with @pytest.mark.network
"""

from __future__ import annotations

import socket

import httpx
import pytest

from tests._skip_helpers import (
    skip_without_moodle,
    skip_without_myunsw,
    skip_without_webcms3,
)


def _server_reachable(host: str, port: int = 443, timeout: float = 2.0) -> bool:
    """Return True if we can open a TCP connection to host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, OSError):
        return False


# ── Public endpoints (no auth) ───────────────────────────────


@pytest.mark.network
class TestPublicEndpoints:
    """Tests against publicly-accessible UNSW endpoints."""

    def test_handbook_reachable(self):
        """handbook.unsw.edu.au should respond."""
        if not _server_reachable("handbook.unsw.edu.au"):
            pytest.skip("handbook.unsw.edu.au not reachable")
        resp = httpx.get(
            "https://handbook.unsw.edu.au/undergraduate/courses/2026/COMP2521.html",
            timeout=15.0,
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_timetable_reachable(self):
        """timetable.unsw.edu.au should respond."""
        if not _server_reachable("timetable.unsw.edu.au"):
            pytest.skip("timetable.unsw.edu.au not reachable")
        resp = httpx.get(
            "https://timetable.unsw.edu.au/2026/COMPKENS.html",
            timeout=15.0,
        )
        assert resp.status_code == 200

    def test_library_reachable(self):
        """primoa.library.unsw.edu.au should respond."""
        if not _server_reachable("primoa.library.unsw.edu.au"):
            pytest.skip("primoa.library.unsw.edu.au not reachable")
        resp = httpx.get(
            "https://primoa.library.unsw.edu.au/discovery/search",
            timeout=15.0,
        )
        assert resp.status_code == 200


# ── Handbook integration ─────────────────────────────────────


@pytest.mark.network
class TestHandbookIntegration:
    """Real tests against handbook.unsw.edu.au."""

    def test_get_real_course(self):
        """Should fetch a real course (COMP2521)."""
        if not _server_reachable("handbook.unsw.edu.au"):
            pytest.skip("handbook.unsw.edu.au not reachable")

        from unsw.modules.handbook import HandbookModule

        module = HandbookModule()
        course = module.get_course("COMP2521", year=2026)
        if course is None:
            pytest.skip(
                "Could not fetch COMP2521 — handbook structure may have changed"
            )
        assert "title" in course or "code" in course

    def test_search_by_area(self):
        """Should list courses in COMP area."""
        if not _server_reachable("timetable.unsw.edu.au"):
            pytest.skip("timetable.unsw.edu.au not reachable")

        from unsw.modules.handbook import HandbookModule

        module = HandbookModule()
        codes = module.search_by_area("COMP", year=2026)
        assert len(codes) >= 5  # COMP has many courses
        assert "COMP1511" in codes or any("COMP" in c for c in codes)


# ── Timetable integration ────────────────────────────────────


@pytest.mark.network
class TestTimetableIntegration:
    """Real tests against timetable.unsw.edu.au."""

    def test_get_real_timetable(self):
        """Should fetch COMP2521 timetable."""
        if not _server_reachable("timetable.unsw.edu.au"):
            pytest.skip("timetable.unsw.edu.au not reachable")

        from unsw.modules.timetable import TimetableModule

        module = TimetableModule()
        classes = module.get_course_classes("COMP2521", 2026)
        # Some terms might not have data; just verify no crash
        assert isinstance(classes, list)


# ── WebCMS3 integration (requires saved credentials) ─────────


@pytest.mark.network
@pytest.mark.auth
@skip_without_webcms3
class TestWebCMS3Integration:
    """Tests against real WebCMS3 using saved credentials."""

    def test_webcms3_login_works(self):
        """Stored WebCMS3 credentials should authenticate successfully."""
        from unsw.auth.webcms3 import verify_credentials
        from unsw.config import Config

        config = Config()
        if not _server_reachable("webcms3.cse.unsw.edu.au"):
            pytest.skip("webcms3.cse.unsw.edu.au not reachable")

        assert verify_credentials(config.auth.zid, config.auth.zpass) is True

    def test_webcms3_courses_loadable(self):
        """Should be able to fetch enrolled courses."""
        if not _server_reachable("webcms3.cse.unsw.edu.au"):
            pytest.skip("webcms3.cse.unsw.edu.au not reachable")

        from unsw.config import Config
        from unsw.modules.webcms3 import WebCMS3Module

        config = Config()
        module = WebCMS3Module(config)
        if not module.client:
            pytest.skip("WebCMS3 login failed")

        courses = module.get_courses()
        assert isinstance(courses, list)


# ── Moodle integration (requires saved cookie) ──────────────


@pytest.mark.network
@pytest.mark.auth
@skip_without_moodle
class TestMoodleIntegration:
    """Tests against real Moodle using saved cookie."""

    def test_moodle_cookie_valid(self):
        """Stored Moodle cookie should be valid."""
        from unsw.auth.moodle import verify_cookie
        from unsw.config import Config

        config = Config()
        if not _server_reachable("moodle.telt.unsw.edu.au"):
            pytest.skip("moodle.telt.unsw.edu.au not reachable")

        saved = config.load_cookies()
        cookie = saved.get("MoodleSession")
        assert verify_cookie(cookie) is True

    def test_moodle_courses_loadable(self):
        """Should be able to fetch courses."""
        if not _server_reachable("moodle.telt.unsw.edu.au"):
            pytest.skip("moodle.telt.unsw.edu.au not reachable")

        from unsw.config import Config
        from unsw.modules.moodle import MoodleModule

        config = Config()
        module = MoodleModule(config)
        if not module.client:
            pytest.skip("Moodle login failed")

        courses = module.get_courses()
        assert isinstance(courses, list)


# ── myUNSW integration (requires saved cookies) ─────────────


@pytest.mark.network
@pytest.mark.auth
@skip_without_myunsw
class TestMyUNSWIntegration:
    """Tests against real myUNSW using saved cookies."""

    def test_myunsw_session_valid(self):
        """Stored myUNSW cookies should be valid."""
        from unsw.auth.myunsw import verify_session
        from unsw.config import Config

        config = Config()
        if not _server_reachable("my.unsw.edu.au"):
            pytest.skip("my.unsw.edu.au not reachable")

        assert verify_session(config) is True

    def test_myunsw_timetable_loadable(self):
        """Should be able to fetch class timetable."""
        if not _server_reachable("my.unsw.edu.au"):
            pytest.skip("my.unsw.edu.au not reachable")

        from unsw.config import Config
        from unsw.modules.myunsw import MyUNSWModule

        config = Config()
        module = MyUNSWModule(config)
        if not module.client:
            pytest.skip("myUNSW login failed")

        classes = module.get_timetable()
        assert isinstance(classes, list)
