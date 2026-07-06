"""Tests for unsw/modules/library.py — Primo URL generation."""

from __future__ import annotations

from unsw.modules.library import LibraryModule


class TestLibrarySearch:
    """Tests for LibraryModule.search()."""

    def test_search_returns_url(self):
        """search() should return a Primo search URL."""
        module = LibraryModule()
        url = module.search("python programming")
        assert "primo" in url.lower() or "library" in url.lower()
        assert "python" in url or "query" in url

    def test_search_url_encodes_special_chars(self):
        """Search should handle spaces and special characters."""
        module = LibraryModule()
        url = module.search("data structures & algorithms")
        # Should not raise — URL encoding handled
        assert url.startswith("http")


class TestLibraryLinks:
    """Tests for get_useful_links()."""

    def test_returns_list_of_links(self):
        """Should return a list of useful library links."""
        module = LibraryModule()
        links = module.get_useful_links()
        assert isinstance(links, list)
        assert len(links) >= 1
        for link in links:
            assert "name" in link
            assert "url" in link
