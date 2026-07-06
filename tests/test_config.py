"""Tests for unsw/config.py — config persistence and cookie merge logic."""

from __future__ import annotations

import json

import pytest

from unsw.config import AuthConfig, Config, DisplayConfig


class TestAuthConfig:
    """Tests for the AuthConfig model."""

    def test_default_values(self):
        """Empty AuthConfig should have safe defaults."""
        auth = AuthConfig()
        assert auth.zid == ""
        assert auth.zpass == ""
        assert auth.use_keyring is False
        assert auth.moodle_session_cookie == ""

    def test_set_zid(self):
        """Can set and read zID."""
        auth = AuthConfig(zid="z1234567")
        assert auth.zid == "z1234567"

    def test_set_zpass(self):
        """Can set and read zPass."""
        auth = AuthConfig(zpass="secret")
        assert auth.zpass == "secret"

    def test_set_moodle_cookie(self):
        """Can set MoodleSession cookie."""
        auth = AuthConfig(moodle_session_cookie="abc123")
        assert auth.moodle_session_cookie == "abc123"


class TestDisplayConfig:
    """Tests for DisplayConfig."""

    def test_default_format_is_table(self):
        config = DisplayConfig()
        assert config.format == "table"

    def test_color_default_true(self):
        config = DisplayConfig()
        assert config.color is True

    def test_custom_format(self):
        config = DisplayConfig(format="json")
        assert config.format == "json"


class TestConfigPersistence:
    """Tests for config save/load and cookie merge behavior."""

    def test_save_and_load_round_trip(self, isolated_config: Config):
        """Saving and loading should preserve values."""
        isolated_config.auth.zid = "z9999999"
        isolated_config.auth.zpass = "secret"
        isolated_config.save()

        # Load fresh
        loaded = Config()
        assert loaded.auth.zid == "z9999999"
        assert loaded.auth.zpass == "secret"

    def test_load_missing_config_returns_defaults(self, isolated_config: Config):
        """Loading when config file is missing should return defaults."""
        # isolated_config fixture provides a fresh empty temp dir
        assert isolated_config.auth.zid == ""
        assert isolated_config.auth.zpass == ""

    def test_save_cookies_creates_file(self, isolated_config: Config):
        """save_cookies should create the cookie file."""
        isolated_config.save_cookies({"test": "value"})
        assert isolated_config.load_cookies() == {"test": "value"}

    def test_save_cookies_merges_with_existing(self, isolated_config: Config):
        """save_cookies with merge=True should preserve existing cookies."""
        # Save Moodle cookie
        isolated_config.save_cookies({"MoodleSession": "moodle_abc"})
        # Save WebCMS3 cookie — should NOT delete Moodle
        isolated_config.save_cookies({"webcms3_session": "webcms3_xyz"})

        cookies = isolated_config.load_cookies()
        assert cookies.get("MoodleSession") == "moodle_abc"
        assert cookies.get("webcms3_session") == "webcms3_xyz"

    def test_save_cookies_overwrites_same_key(self, isolated_config: Config):
        """save_cookies should update existing values for the same key."""
        isolated_config.save_cookies({"MoodleSession": "old_value"})
        isolated_config.save_cookies({"MoodleSession": "new_value"})

        cookies = isolated_config.load_cookies()
        assert cookies["MoodleSession"] == "new_value"

    def test_save_cookies_overwrite_mode(self, isolated_config: Config):
        """merge=False should fully replace cookies."""
        isolated_config.save_cookies({"MoodleSession": "abc"})
        isolated_config.save_cookies({"webcms3": "xyz"}, merge=False)

        cookies = isolated_config.load_cookies()
        assert "MoodleSession" not in cookies
        assert cookies["webcms3"] == "xyz"

    def test_load_cookies_missing_file_returns_empty(self, isolated_config: Config):
        """load_cookies should return empty dict when no file exists."""
        assert isolated_config.load_cookies() == {}

    def test_load_cookies_corrupt_file_returns_empty(self, isolated_config: Config):
        """load_cookies should gracefully handle corrupt JSON."""
        from unsw.config import COOKIE_FILE

        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(COOKIE_FILE, "w") as f:
            f.write("{ not valid json")

        assert isolated_config.load_cookies() == {}

    def test_use_keyring_strips_passwords_on_save(self, isolated_config: Config):
        """When use_keyring=True, save() should not write zpass to YAML."""
        isolated_config.auth.zid = "z1234567"
        isolated_config.auth.zpass = "should_not_persist"
        isolated_config.auth.use_keyring = True
        isolated_config.save()

        # Read the raw YAML to confirm the password was stripped
        import yaml

        from unsw.config import CONFIG_FILE

        with open(CONFIG_FILE) as f:
            raw = yaml.safe_load(f)
        assert raw["auth"]["zid"] == "z1234567"
        assert raw["auth"]["zpass"] == ""
        assert raw["auth"]["use_keyring"] is True

    def test_ensure_data_dir_creates_directory(self, isolated_config: Config):
        """ensure_data_dir should create the data dir if missing."""
        from pathlib import Path

        data_dir = isolated_config.ensure_data_dir()
        assert data_dir.exists()
        assert data_dir.is_dir()


class TestConfigAutoLoad:
    """Tests for the Config auto-load behavior."""

    def test_config_load_classmethod(self, isolated_config: Config):
        """Config.load() should be equivalent to Config()."""
        isolated_config.auth.zid = "z1111111"
        isolated_config.save()

        # Should pick up the saved value
        loaded = Config.load()
        assert loaded.auth.zid == "z1111111"
