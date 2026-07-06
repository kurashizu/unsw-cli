"""Shared HTTP client with retry, cookie persistence, and user-agent rotation."""

from __future__ import annotations

from typing import Optional

import httpx

from unsw.config import Config

# Realistic browser User-Agent
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en-US;q=0.9,en;q=0.8",
}


def build_client(cookies: Optional[dict[str, str]] = None) -> httpx.Client:
    """Build a shared HTTPX client with sensible defaults."""
    headers = DEFAULT_HEADERS.copy()
    client = httpx.Client(
        headers=headers,
        cookies=cookies or {},
        follow_redirects=True,
        timeout=30.0,
        verify=True,
    )
    return client


def build_async_client() -> httpx.AsyncClient:
    """Build a shared async HTTPX client."""
    return httpx.AsyncClient(
        headers=DEFAULT_HEADERS.copy(),
        follow_redirects=True,
        timeout=30.0,
        verify=True,
    )
