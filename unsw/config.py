"""Configuration management for UNSW CLI.

Stores credentials, cookies, and preferences in a local YAML file.
Credentials are optionally stored in the system keyring for security.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path.home() / ".config" / "unsw-cli"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
COOKIE_FILE = CONFIG_DIR / "cookies.json"


class AuthConfig(BaseModel):
    """Authentication credentials for various UNSW platforms."""

    zid: str = ""
    zpass: str = ""
    use_keyring: bool = False
    moodle_session_cookie: str = ""  # MoodleSession cookie


class DisplayConfig(BaseModel):
    """Display preferences."""

    format: str = "table"  # table, json, csv
    color: bool = True


class Config(BaseModel):
    """Main configuration.

    Auto-loads from disk when constructed with no arguments.
    Use Config() to get the current saved config.
    """

    auth: AuthConfig = Field(default_factory=AuthConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    data_dir: str = str(CONFIG_DIR / "data")

    def __init__(self, **data):
        """Auto-load from CONFIG_FILE when called with no arguments."""
        if not data and CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    raw = yaml.safe_load(f)
                if raw:
                    super().__init__(**raw)
                    return
            except Exception:
                pass
        super().__init__(**data)

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from disk (equivalent to Config())."""
        return cls()

    def save(self) -> None:
        """Save configuration to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Don't save passwords to yaml if using keyring
        data = self.model_dump()
        if self.auth.use_keyring:
            data["auth"]["zpass"] = ""
            data["auth"]["moodle_session_cookie"] = ""
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

    def save_cookies(self, cookies: dict[str, str], merge: bool = True) -> None:
        """Save cookies to disk as JSON.

        By default (merge=True), merges with existing cookies so that
        different platform cookies don't overwrite each other.
        """
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if merge:
            existing = self.load_cookies()
            existing.update(cookies)
            cookies = existing
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

    def load_cookies(self) -> dict[str, str]:
        """Load cookies from disk."""
        if not COOKIE_FILE.exists():
            return {}
        try:
            with open(COOKIE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def ensure_data_dir(self) -> Path:
        """Ensure the data directory exists."""
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
