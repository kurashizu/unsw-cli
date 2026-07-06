"""Base module class for all platform modules."""

from __future__ import annotations

from typing import Any

import httpx


class BaseModule:
    """Base class for all UNSW platform modules."""

    name = "base"
    description = ""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            },
        )
