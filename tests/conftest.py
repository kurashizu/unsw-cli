"""Shared pytest fixtures and configuration.

Provides:
- `isolated_config`: A Config object pointed at a temporary directory
- `cli_runner`: Typer CLI test runner
- `network`: Marker to skip tests that require real network access
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from unsw.config import CONFIG_DIR, CONFIG_FILE, COOKIE_FILE, AuthConfig, Config
from unsw.utils.output import console

# ── Network marker ────────────────────────────────────


# Markers are configured in pytest.ini


# ── Isolated config fixtures ─────────────────────────────────


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Provide a Config object that points at a temporary directory.

    This isolates tests from the real user config (~/.config/unsw-cli/).
    The temporary config and cookies files are auto-created and cleaned up.
    """
    test_config_dir = tmp_path / "unsw-cli-config"
    test_config_dir.mkdir(parents=True, exist_ok=True)

    test_config_file = test_config_dir / "config.yaml"
    test_cookie_file = test_config_dir / "cookies.json"

    # Patch the global paths to point at our temp directory.
    # We must patch BOTH the unsw.config module attributes AND any modules
    # that have imported these references at load time.
    monkeypatch.setattr("unsw.config.CONFIG_DIR", test_config_dir)
    monkeypatch.setattr("unsw.config.CONFIG_FILE", test_config_file)
    monkeypatch.setattr("unsw.config.COOKIE_FILE", test_cookie_file)

    # Reload unsw.config so default_factory closures pick up the new paths
    import importlib

    import unsw.config as cfg_mod

    importlib.reload(cfg_mod)

    # Re-export the reloaded symbols
    Config = cfg_mod.Config
    AuthConfig = cfg_mod.AuthConfig

    # Patch ALL modules that imported the old paths
    import sys

    for module_name in list(sys.modules.keys()):
        mod = sys.modules.get(module_name)
        if mod is None:
            continue
        if hasattr(mod, "CONFIG_DIR") and getattr(mod, "CONFIG_DIR", None) is not None:
            # Only patch if it points to the same path object that we replaced
            try:
                if str(mod.CONFIG_DIR).endswith(".config/unsw-cli"):
                    monkeypatch.setattr(mod, "CONFIG_DIR", test_config_dir)
            except Exception:
                pass
        if hasattr(mod, "CONFIG_FILE"):
            try:
                if str(mod.CONFIG_FILE).endswith("config.yaml"):
                    monkeypatch.setattr(mod, "CONFIG_FILE", test_config_file)
            except Exception:
                pass
        if hasattr(mod, "COOKIE_FILE"):
            try:
                if str(mod.COOKIE_FILE).endswith("cookies.json"):
                    monkeypatch.setattr(mod, "COOKIE_FILE", test_cookie_file)
            except Exception:
                pass

    return Config()


@pytest.fixture
def config_with_webcms3(isolated_config: Config) -> Config:
    """Config with WebCMS3 credentials pre-populated."""
    isolated_config.auth.zid = "z5530104"
    isolated_config.auth.zpass = "Zzymysoul0914."
    isolated_config.save()
    return isolated_config


@pytest.fixture
def config_with_moodle_cookie(isolated_config: Config) -> Config:
    """Config with a MoodleSession cookie pre-populated."""
    isolated_config.save_cookies(
        {
            "MoodleSession": "fake_cookie_for_testing",
            "webcms3": "fake_webcms3_session",
        }
    )
    return isolated_config


# ── CLI runner ───────────────────────────────────────────────


@pytest.fixture
def cli_runner() -> CliRunner:
    """Provide a Typer CLI test runner."""
    return CliRunner()


# ── Sample data fixtures ────────────────────────────────────


@pytest.fixture
def handbook_html() -> str:
    """Sample SSR-rendered HTML for a UNSW Handbook course page."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <script id="__NEXT_DATA__" type="application/json">
        {
            "props": {
                "pageProps": {
                    "pageContent": {
                        "cl_code": "COMP2521",
                        "title": "Data Structures and Algorithms",
                        "credit_points": "6 UOC",
                        "description": "Data structures and algorithms.",
                        "offered_terms": ["T1", "T2", "T3"]
                    }
                }
            }
        }
        </script>
    </head>
    <body></body>
    </html>
    """


@pytest.fixture
def timetable_html() -> str:
    """Sample HTML for a UNSW Timetable page (matches actual structure)."""
    return """
    <html>
    <body>
    <table>
        <tr>
            <td>Teaching Period One</td>
        </tr>
        <tr>
            <td>Activity</td>
            <td>Period</td>
            <td>Class</td>
            <td>Section</td>
            <td>Status</td>
            <td>Enrols</td>
            <td>Schedule</td>
        </tr>
        <tr>
            <td>Lecture</td>
            <td>Mon 13:00-15:00</td>
            <td>1234</td>
            <td>T13A</td>
            <td>Open</td>
            <td>100/200</td>
            <td>weekly</td>
        </tr>
        <tr>
            <td>Tutorial</td>
            <td>Wed 14:00-16:00</td>
            <td>1235</td>
            <td>W14B</td>
            <td>Open</td>
            <td>15/25</td>
            <td>weekly</td>
        </tr>
    </table>
    </body>
    </html>
    """


@pytest.fixture
def moodle_dashboard_html() -> str:
    """Sample HTML for a Moodle dashboard with course cards."""
    return """
    <html>
    <body>
    <div data-region="course-content">
        <div class="card-body">
            <a href="/course/view.php?id=12345">COMP9444 - Neural Networks</a>
        </div>
        <div class="card-body">
            <a href="/course/view.php?id=12346">COMP9319 - Web Data Compression</a>
        </div>
    </div>
    </body>
    </html>
    """


@pytest.fixture
def webcms3_dashboard_html() -> str:
    """Sample HTML for a WebCMS3 dashboard with nav bar courses."""
    return """
    <html>
    <body>
    <nav>
        <a href="/COMP6733/26T2/">COMP6733</a>
        <a href="/COMP9319/26T2/">COMP9319</a>
        <a href="/COMP9444/26T2/">COMP9444</a>
    </nav>
    <main>
        <h1>Dashboard</h1>
    </main>
    </body>
    </html>
    """


@pytest.fixture
def myunsw_login_response_html() -> str:
    """Sample myUNSW response after login (PeopleSoft dashboard)."""
    return """
    <html>
    <body>
        <table summary="Enrolled Classes">
            <tr>
                <th>Section</th>
                <th>Activity</th>
                <th>Day</th>
                <th>Time</th>
                <th>Location</th>
            </tr>
            <tr>
                <td>COMP6733-Lec-01</td>
                <td>Lecture</td>
                <td>Mon</td>
                <td>13:00-15:00</td>
                <td>UNSW Bus 201</td>
            </tr>
        </table>
    </body>
    </html>
    """
