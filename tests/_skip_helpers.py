"""Helpers to skip integration/auth tests when prerequisites aren't met."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from unsw.config import CONFIG_DIR, COOKIE_FILE, Config


def has_real_config() -> bool:
    """Return True if the user has a real config in ~/.config/unsw-cli/."""
    return CONFIG_DIR.exists() and (CONFIG_DIR / "config.yaml").exists()


def has_moodle_cookie() -> bool:
    """Return True if a MoodleSession cookie is stored."""
    if not COOKIE_FILE.exists():
        return False
    try:
        with open(COOKIE_FILE) as f:
            cookies = json.load(f)
        return bool(cookies.get("MoodleSession"))
    except Exception:
        return False


def has_webcms3_credentials() -> bool:
    """Return True if WebCMS3 credentials are configured."""
    if not has_real_config():
        return False
    config = Config()
    return bool(config.auth.zid and config.auth.zpass)


def has_myunsw_cookies() -> bool:
    """Return True if myUNSW session cookies are stored."""
    if not COOKIE_FILE.exists():
        return False
    try:
        with open(COOKIE_FILE) as f:
            cookies = json.load(f)
        return any(k.startswith("myunsw_") for k in cookies)
    except Exception:
        return False


skip_without_moodle = pytest.mark.skipif(
    not has_moodle_cookie(),
    reason="No MoodleSession cookie in ~/.config/unsw-cli/cookies.json",
)

skip_without_webcms3 = pytest.mark.skipif(
    not has_webcms3_credentials(),
    reason="No WebCMS3 credentials in ~/.config/unsw-cli/config.yaml",
)

skip_without_myunsw = pytest.mark.skipif(
    not has_myunsw_cookies(),
    reason="No myUNSW cookies in ~/.config/unsw-cli/cookies.json",
)
